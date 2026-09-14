# South East Water integration – design document

Version 2.0 (pure-HTTP rewrite). Last updated 2026-09-14.

This document records *why* the integration is built the way it is. The README covers how to use
it; the module docstrings cover how each piece works.

---

## 1. Goals

| # | Goal | Outcome |
|---|---|---|
| G1 | Daily mains water usage from `my.southeastwater.com.au` into Home Assistant. | Long-term statistics for the Energy dashboard plus live sensors. |
| G2 | No browser automation. | Version 1.x drove the portal through Browserless/Puppeteer. Every step of the portal flow was proven to be plain HTTP, so 2.0 uses `aiohttp` only. |
| G3 | Cope with the portal's mandatory one-time code. | Code required once at setup and again only when the session dies; sessions survive restarts. |
| G4 | Cope with the portal publishing readings late. | Every poll re-fetches and re-imports a trailing window. |
| G5 | Keep 1.x history. | Same statistic id and row timestamps, so existing rows are overwritten, never duplicated. |

Non-goals: recycled water (author has no such meter), Yarra Valley Water (same Salesforce backend but
untestable), YAML configuration, PyPI packaging.

## 2. Decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | Transport is `aiohttp`; the client lives inside the integration (`sew_client.py`) rather than on PyPI. | Personal HACS integration; one less release pipeline. The client stays framework-free so it can be tested offline. |
| D2 | Daily resolution for everything the user sees. | Matches how the portal presents usage and how the Energy dashboard aggregates water. |
| D3 | First run imports 90 days; every poll re-imports the last 30 days. | 90 days fits one batched request. 30 days comfortably covers the portal's publication lag and corrections. |
| D4 | Statistics **and** sensors. | A sensor cannot hold retroactive history; a statistic cannot drive automations or cards. |
| D5 | Daily poll pinned to 02:00 local when the interval is the default (1440 min). | The previous day's readings are usually published by then; a fixed interval from HA start time would drift. |
| D6 | Zero-reading days are shown as "not published" by the sensors but imported as 0 L. | The portal returns 24 zeros both for unpublished days and for old dates; the trailing re-import corrects a 0 once real data appears, so nothing is lost by importing it. |
| D7 | Session cookies persisted in the config entry and refreshed after every poll. | This is what makes MFA a once-per-session event instead of once-per-poll, and what lets sessions survive restarts. |
| D8 | Username and password stored in the config entry. | HA has no encrypted vault for integrations; `.storage` (mode 0600) is the standard. Storing the password means re-authentication needs only a new code. The password alone cannot open a session because the portal always demands a code. |
| D9 | Re-authentication is HA's standard reauth flow: choose channel → enter code. | No custom notifications; the repair card is what users already know. |
| D10 | Statistic rows stamped at 11:00 local; daily sensor is `VOLUME`/`MEASUREMENT`. | Both inherited from 1.x for continuity of stored data and recorder history (G5). |
| D11 | Config-entry `VERSION = 2`; 1.x entries are refused, not migrated. | 1.x entries hold Browserless settings and no session; there is nothing to migrate. Statistics are unaffected. |
| D12 | Tests cover the client only (offline, `aioresponses`). HA-level tests deferred. | The client is where the risk is; HA plumbing is thin and follows core patterns. |
| D14 | Throttling is detected from Salesforce's Apex error text ("concurrent requests limit exceeded"), plus HTTP 429/503 with `Retry-After` for good measure, and surfaced as `SewBusyError` → `UpdateFailed(retry_after=15 min)`. Usage batches are 30 actions and the daily poll carries up to 10 min of random jitter. | The core Salesforce platform does not use 429 for Aura requests; the limit that applies is the org-wide cap of 10 synchronous Apex requests running > 5 s, shared by every portal user. Keeping each batch under ~3 s stays out of that pool, jitter avoids installations colliding, and a short retry beats waiting for the next day. |
| D15 | `clientOutOfSync` reloads the home page for a fresh Aura context and retries once. | It means the cached `fwuid` is stale after a Salesforce release, not that the session is dead; treating it as an auth failure would demand a needless one-time code. |
| D13 | Billing-account ID, meter record ID and meter serial are not entities and not on the device card. | They identify the customer's account; as entities they would be persisted in the recorder and appear in every state dump. They stay in the config entry (needed for API calls), are redacted from diagnostics, and are logged once at debug level on startup for checking. |

## 3. Architecture

```
┌──────────────┐   ConfigFlow (setup / reauth / options)
│  config_flow │──────────────┐
└──────────────┘              │ cookies, ids, credentials
                              ▼
┌──────────────┐   ┌───────────────────┐   ┌────────────────────┐
│  __init__    │──▶│  SewCoordinator   │──▶│ recorder statistics│  sew_water:water_usage_mains
│  (setup,     │   │  (poll, import,   │   └────────────────────┘
│   services)  │   │   cookie refresh) │──▶ SewData ──▶ sensor entities
└──────────────┘   └─────────┬─────────┘
                             │ SewClient (aiohttp session with cookie jar)
                             ▼
                    my.southeastwater.com.au
```

| Module | Responsibility |
|---|---|
| `sew_client.py` | Portal protocol only. No HA imports. Raises `SewAuthError`, `SewConnectionError`, `SewProtocolError`. |
| `config_flow.py` | Setup and reauth steps; options flow. Owns a private HTTP session for the duration of the flow. |
| `coordinator.py` | `DataUpdateCoordinator[SewData]`; window selection, statistics import, cookie persistence, scheduling. |
| `sensor.py` | `CoordinatorEntity` sensors described declaratively (`SewSensorDescription.value_fn`). Usage values only — account identifiers are never entities (D13). |
| `diagnostics.py` | Config-entry diagnostics with credentials, cookies and record ids redacted. |
| `const.py` | Keys, defaults, statistic id, timing constants. |

## 4. Portal protocol

Verified against captures taken 2026-09-13. The portal is Salesforce Experience Cloud; the pieces
in play are the Aura RPC endpoint, a `frontdoor.jsp` session hand-off and a Visualforce/RichFaces
login flow for the one-time code.

| Step | Request | Notes |
|---|---|---|
| 1 | `GET /s/login/` | Page embeds the Aura context (`fwuid`, loaded-app hash) URL-encoded inside `/s/sfsites/l/{…}/bootstrap.js` script URLs. App is `siteforce:loginApp2`, token is `null`. |
| 2 | `POST /s/sfsites/aura` action `apex://cm_LoginAURA/ACTION$login` `{username, password, startUrl:"/"}` | Good credentials → `returnValue` is a `/secur/frontdoor.jsp?sid=…` URL. Bad credentials → `state` is still `SUCCESS`, `returnValue` is the error text. |
| 3 | `GET` the frontdoor URL | Sets `sid`, `sid_Client`, `inst`, `oid`, `__Secure-has-sid` …; 302 → `/apex/PortalMFALoginFlow?retURL=/`. |
| 4 | Parse the MFA form | `form id="j_id0:mfaForm"`, radio `channel` = `Email` / `SMS`, submit `…:j_id26` = "Send code", four `com.salesforce.visualforce.ViewState*` hidden fields. |
| 5 | `POST /PortalMFALoginFlow` with `AJAXREQUEST=_viewRoot`, form id, `channel`, `…:channelRadio`, ViewState×4, send button | Response is a full XHTML page with a **new ViewState**, `otpBox1..6`, `…:otpHidden` and a "Verify" submit. The new ViewState must be carried forward. |
| 6 | `POST /PortalMFALoginFlow` with `otpHidden`, `otpBox1..6`, new ViewState×4, verify button | Success = `Location: /s/` header (the client also accepts `<meta name="Location">`). Failure = the same form again with an error span. |
| 7 | `GET /s/` | Every HTML page load issues a fresh Aura CSRF token in a `__Host-ERIC_PROD-*` cookie; the page names that cookie in its `"eikoocnekot"` bootstrap setting. Context app is `siteforce:communityApp`. A dead session redirects to `/s/login/`. |
| 8 | `POST /s/sfsites/aura` action `aura://ApexActionController/ACTION$execute`, class `MysewUsageBillingGraphController`, method `getUsageData`, params `{baId, meterId, dateFrom, dateTo, resolution:"hourly"}` | One action per day; 30 actions per POST (120 verified to work, 30 keeps each request under the 5 s long-running threshold, see D14). Returns `[{apiDate, readings[24], serialNo, message, status}]`; the client sums the 24 hourly litres. `resolution:"daily"` was never captured and is not used. |
| 9 | ID discovery: `apex://cm_AccountBillingUsageAURA/ACTION$retrieveBillingAccounts` then `…$retrieveSObject` on `Meter_Details__c` | `baId`/`meterId` are Salesforce record ids (`a08…`, `a1K…`), not the account number or meter serial. **Built from notes, not captures – see §9.** |

Every Aura POST sends `aura.context` (mode, app, fwuid, loaded), `aura.pageURI`, `aura.token` and the
`message` JSON, form-encoded. Error mapping: `exceptionEvent` naming `invalidSession` → `SewAuthError`;
`clientOutOfSync` → reload `/s/` and retry once (D15); an action `state: ERROR` or exception message
matching *concurrent requests limit / request limit exceeded / too many requests*, or HTTP 429/503 →
`SewBusyError` with any `Retry-After` seconds (D14); other errors → `SewProtocolError`.

**Throttling on this platform.** Experience Cloud/Aura does not return 429 or `Retry-After` (those
belong to Salesforce's Commerce and Marketing Cloud APIs). What applies is the org-wide *concurrent
long-running Apex* limit: at most 10 synchronous requests running longer than 5 s, across all users of
the org, after which every Apex request is refused with the error text above until one finishes.
Site page-view and login allocations are administrative and give no client-side signal; session reuse
keeps our contribution to one page view per day and one login per session.

## 5. Session lifecycle

```
setup ──▶ login+MFA ──▶ cookies saved in entry.data
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         │
   poll: import cookies ─▶ GET /s/ ─▶ token ─▶ usage ─▶ export cookies ─▶ entry.data
              │ (redirect to login / invalidSession)
              ▼
   ConfigEntryAuthFailed ──▶ HA reauth card ──▶ channel ─▶ code ─▶ cookies replaced ─▶ reload
```

- The coordinator's session is created per config entry with its own cookie jar
  (`async_create_clientsession(hass, cookie_jar=CookieJar())`) so portal cookies never mix with HA's
  shared session, and is closed on unload.
- `export_cookies` filters the jar to the portal domain and produces a JSON-serialisable list.
  Cookies are written back only when they changed, to avoid needless entry updates.
- Measured lifetime: a session kept alive with a request every 30 minutes survived 22 h with no
  failures. The 24 h-idle case is being measured by a daily cron on the dev box (see §9).

## 6. Statistics design

- One external statistic, `sew_water:water_usage_mains`, `has_sum=True`, `mean_type=NONE`,
  `unit_class="volume"`, unit litres.
- One row per day at **11:00 local** (`STATISTIC_HOUR`), `state` = that day's litres, `sum` =
  running total.
- Re-import rule: the running total is rebuilt from the newest row *before* the window
  (`statistics_during_period`, looking back up to ten years), then each day in the window is written
  with `async_add_external_statistics`. Rows are keyed by start time, so the import overwrites in
  place and stays consistent even when an earlier day inside the window changes.
- First run is detected by the absence of any row (`get_last_statistics`), which is why an upgrade
  from 1.x takes the 30-day path rather than re-backfilling.
- `total_usage` sensor = the running total after the last imported day. It is `total_increasing`
  for card/automation use only; the README tells users to point the Energy dashboard at the
  statistic, because a once-a-day sensor would be attributed to the poll minute.

## 7. Scheduling

`SewCoordinator._interval` recomputes `update_interval` after every poll:

- interval == 1440 → `next 02:00 local − now` plus 0–10 min of random jitter (never a fixed 24 h, so it does not drift, and installations do not collide);
- any other value → `timedelta(minutes=interval)` (minimum 60, enforced by the options selector).

A `SewBusyError` from the poll becomes `UpdateFailed(retry_after=…)`: the portal's `Retry-After` if it sent one, else 15 minutes; the coordinator honours it for the next attempt and the daily schedule resumes after.

`import_from_date` bypasses the window and imports `start..yesterday` in the same code path, then
pushes the result to entities with `async_set_updated_data`.

## 8. Security and privacy

- Credentials, cookies and Salesforce record ids are redacted from diagnostics; identifiers are never entities (D13).
- Nothing sensitive is logged; the only debug line at auth time logs the portal's *rejection text*,
  never inputs.
- The client sends a fixed browser user agent; no third-party services are contacted.
- The probe tooling that captured the protocol lives outside the repository.

## 9. Open items

| Item | Status |
|---|---|
| Live verification of `async_discover_ids` (`retrieveBillingAccounts` params/response; the `Meter_Details__c` query's where-clause field). | Helpers ready in `/root/sew_probe/live_client_check.py` and `discover_capture.py`; run after the 10:45 UTC session cron on 2026-09-15. |
| Wrong-code response text and whether the a4j redirect arrives as a header or a meta tag. | Client handles both forms; unverified which the portal uses. |
| 24 h-idle session lifetime. | Daily cron measuring since 2026-09-14 10:43 UTC. Determines how often users will see the reauth card. |
| First end-to-end run in a real Home Assistant. | Pending a one-time code from the account owner. |
| HA-level tests (`pytest-homeassistant-custom-component`). | Deferred (D12). |

## 10. Testing

`tests/test_sew_client.py` (27 cases, offline, `aioresponses`) covers: login success / bad
credentials / no-MFA / maintenance page / 5xx / network failure; MFA field names, ViewState carry-
forward, wrong code with retry, code length, step ordering; session alive / dead / token-less and
cookie round-trip; id discovery; usage summing, batching across 60-action pages, unavailable days,
`invalidSession`, action errors and non-JSON responses.

Tooling: `ruff` (120 columns, Google docstrings, HA import order), `mypy --strict`, `pytest` with
`asyncio_mode = auto`. Configuration in `pyproject.toml`.

## 11. History

| Version | Summary |
|---|---|
| 1.x (`v0-browserless` tag, `archive/browserless` branch) | Browserless/Puppeteer script logs in, scrapes the Aura token, batches usage calls. Broke when the portal added mandatory MFA and changed its Aura bootstrap. |
| 2.0 | This document. |
