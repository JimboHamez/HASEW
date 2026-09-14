# South East Water

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
![GitHub Release](https://img.shields.io/github/v/release/JimboHamez/HASEW?style=for-the-badge)
[![hacs_downloads](https://img.shields.io/github/downloads/JimboHamez/HASEW/latest/total?style=for-the-badge)](https://github.com/JimboHamez/HASEW/releases/latest)
![GitHub License](https://img.shields.io/github/license/JimboHamez/HASEW?style=for-the-badge)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/JimboHamez/HASEW?style=for-the-badge)
![Maintenance](https://img.shields.io/maintenance/yes/2026?style=for-the-badge)

[![Tests](https://github.com/JimboHamez/HASEW/actions/workflows/test.yml/badge.svg)](https://github.com/JimboHamez/HASEW/actions/workflows/test.yml)
[![Validate](https://github.com/JimboHamez/HASEW/actions/workflows/validate.yaml/badge.svg)](https://github.com/JimboHamez/HASEW/actions/workflows/validate.yaml)
[![hassfest](https://github.com/JimboHamez/HASEW/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/JimboHamez/HASEW/actions/workflows/hassfest.yaml)
[![Security](https://github.com/JimboHamez/HASEW/actions/workflows/security.yml/badge.svg)](https://github.com/JimboHamez/HASEW/actions/workflows/security.yml)

Daily mains water usage from the [South East Water](https://my.southeastwater.com.au) customer portal, straight into Home Assistant.

It gives you:

- **Energy dashboard water** — one long-term statistic, `sew_water:water_usage_mains`, with a row for every day.
- **Daily sensors** — yesterday's litres (with the 24 hourly readings as attributes), a running total and the reading date.
- **One login** — sign in once with your portal email, password and a one-time code; the session is kept and re-used, and survives restarts.
- **Late data handled** — the portal publishes readings a day or two late and sometimes corrects them, so every poll re-imports the last 30 days.
- **Painless re-login** — when the portal finally expires the session, Home Assistant's standard *Reauthentication required* card asks only for a new code.

**No Browserless, no Chrome, no add-ons** — the integration talks to the portal directly over HTTPS.

---

## Why this exists

South East Water's digital meters report hourly usage to the customer portal, but the portal only shows it in a web page — there is no API, no export and no way to see it next to your other utilities in Home Assistant.

The 1.x version of this integration drove the portal through a headless browser (Browserless). That worked until the portal made a one-time code mandatory on every login and changed how its pages bootstrap; the browser script could no longer find the session token, and every poll would have needed a fresh code anyway.

Version 2 maps the whole login, code and usage flow to plain HTTP requests. Setup asks for the code once, the resulting session is kept and refreshed on every poll, and the browser dependency is gone. It is smaller, faster to poll and much easier to keep working.

---

## 🆕 What's new in v2.0.0b1

**Beta.** The Browserless-based scraper is replaced by a pure-HTTP client. Setup now walks through the portal's one-time code (email or SMS), sessions are stored and re-used across polls and restarts, and re-authentication when a session expires is Home Assistant's standard reauth card. Polling runs at 02:00 local time and re-imports the last 30 days so late-published readings are filled in automatically.

**Upgrading?** 1.x config entries cannot be migrated — remove the old entry and add the integration again. Your existing `sew_water:water_usage_mains` statistics are kept and continue seamlessly. Yarra Valley Water and recycled-water support have been removed (see [Compatibility](#compatibility)).

Full history in the [CHANGELOG](CHANGELOG.md) · [release notes](https://github.com/JimboHamez/HASEW/releases/tag/v2.0.0b1).

---

## Prerequisites

### 1. Portal account

A working login for [my.southeastwater.com.au](https://my.southeastwater.com.au) on an account with a **digital meter** (usage appears on the portal's *Usage* page). During setup the portal will send a one-time code to the email address or mobile number on the account, so have that to hand.

### 2. Recorder

Long-term statistics are stored by Home Assistant's [recorder](https://www.home-assistant.io/integrations/recorder/), which is on by default. History lives in the recorder database, not in this integration — removing and re-adding the integration keeps it.

### 3. Energy dashboard (optional)

Only needed if you want the water card on the Energy dashboard. Nothing to set up in advance; see [How it works → Energy dashboard](#energy-dashboard).

---

## Installation

![South East Water sensors in Home Assistant](images/dashboard.png)
<!-- placeholder: capture the device page showing the three sensors -->

### HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/JimboHamez/HASEW` as type **Integration**.
3. Install **South East Water**.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/sew_water/` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.

### Removing the integration

1. **Settings → Devices & Services → South East Water** → ⋮ → **Delete**. This removes the config entry, the stored session and every entity it created.
2. If installed via HACS, HACS → **South East Water** → ⋮ → **Remove**; for a manual install delete `config/custom_components/sew_water/`.
3. Restart Home Assistant.

One thing is deliberately left behind: the **`sew_water:water_usage_mains` statistic** and its history stay in the recorder database, so reinstalling picks up where you left off. To delete it, use *Settings → Developer tools → Statistics* and remove the orphaned entry.

The integration uses only `aiohttp`, which ships with Home Assistant — nothing else to install.

---

## Configuration

**Settings → Devices & Services → Add Integration → South East Water**

The wizard has three steps; steps 2 and 3 only appear when the portal asks for a one-time code (it always does today).

### Step 1 — Sign in
![Step 1 — Sign in](images/config-step1-signin.png)
<!-- placeholder: capture the credentials page -->

| Field | Description |
|---|---|
| Email address | The email you log in to the portal with |
| Password | Your portal password |

### Step 2 — Send code by (only if the portal asks for a code)
![Step 2 — Send code by](images/config-step2-channel.png)
<!-- placeholder: capture the Email / SMS chooser -->

| Field | Default | Description |
|---|---|---|
| Send code by | Email | Where the portal sends the one-time code: **Email** or **Text message (SMS)** |

### Step 3 — One-time code (only if the portal asks for a code)
![Step 3 — One-time code](images/config-step3-code.png)
<!-- placeholder: capture the code entry page -->

| Field | Description |
|---|---|
| One-time code | The 6-digit code the portal just sent. Spaces and dashes are ignored. |

The billing account and meter are discovered automatically once the code is accepted.

### Options

⚙ on the integration entry.

| Field | Default | Description |
|---|---|---|
| Poll interval | 1440 min | Minutes between polls. At the default the poll is pinned to **02:00 local time** every day; any other value (minimum 60) is used as a plain interval. |

### Re-authentication

When the portal expires the stored session, Home Assistant shows a **Reauthentication required** card. Click **Reconfigure**, then:

1. **Sign in again** — press *Request code* (your saved credentials are re-used).
2. **Send code by** — Email or SMS.
3. **One-time code** — enter the code.

If the portal rejects the saved password, an extra **Update password** step appears before the code is requested.

> **Heads up:** the portal requires a one-time code for *every* new login and offers no "remember this device". The integration avoids that by keeping the session alive between polls, so re-authentication should be rare.

---

## How it works

- **Session reuse** — the cookies from the one login you did at setup are stored in the config entry and re-sent on every poll. Each successful poll writes the refreshed cookies back, so the session survives Home Assistant restarts and is not tied to a browser.
- **Trailing re-import** — every poll fetches the last 30 days in one batched request and re-imports them. Statistics rows are keyed by day, so re-importing overwrites in place: late-published days get filled in and corrections are applied without duplicates. The first poll after setup imports 90 days.
- **Statistics and sensors, not one or the other** — a sensor cannot carry retroactive history and a statistic cannot drive a card or an automation, so the integration keeps both. The statistic is the source of truth; the *Total usage* sensor mirrors its running total.
- **02:00 local poll** — the previous day's readings are usually published by then. The next poll is always scheduled as "next 02:00" (plus a few random minutes so every installation doesn't hit the portal at the same second), so it never drifts. If the portal reports it is busy, the poll retries after 15 minutes rather than waiting a day.
- **Zero days** — the portal returns 24 zeros both for an unpublished day and for a genuinely empty one. The *Daily usage* / *Last reading date* sensors skip zero days; statistics import them as 0 L and a later poll corrects them if data appears.

The protocol, the statistics rules and every design decision are in [DESIGN_DOCUMENT.md](DESIGN_DOCUMENT.md).

### Energy dashboard

*Settings → Dashboards → Energy → Water consumption → Add water source* and pick **`sew_water:water_usage_mains`**.

> ⚠️ Use the statistic, not the `Total usage` sensor. The statistic has one row per day with the correct date, including back-filled and corrected days. The sensor only changes once per poll, so the dashboard would attribute a whole day's usage to the minute the poll ran.

---

## Sensors

All entities sit on one device, **South East Water**.

| Sensor | Unit | Description |
|---|---|---|
| `sensor.south_east_water_daily_usage` | L | Most recent published day's usage. Attributes: `reading_date`, `hourly_readings` (24 values). |
| `sensor.south_east_water_total_usage` | L | Running total of every day imported (`total_increasing`). |
| `sensor.south_east_water_last_reading_date` | date | Day the *Daily usage* value belongs to. |

Account identifiers (billing account, meter record ID, meter serial) are deliberately **not** exposed as entities — they identify your account and would otherwise be kept in the recorder. They live only in the config entry, are redacted from diagnostics, and are written once to the log at debug level on startup if you need to check them.

---

## Services

| Service | Description |
|---|---|
| `sew_water.force_import` | Poll the portal now instead of waiting for the next scheduled poll. |
| `sew_water.import_from_date` | Import every day from `start_date` up to yesterday — for example, back to the day your digital meter was installed. |

```yaml
action: sew_water.import_from_date
data:
  start_date: "2026-01-01"
```

---

## Roadmap

- **Recycled water** — not supported; the author has no recycled meter to test against. Contributions welcome.
- **Yarra Valley Water** — runs on the same Salesforce Experience Cloud backend and the client could be adapted, but it is untested and not included.
- **Session lifetime** — measuring how long the portal keeps an idle session so the re-authentication cadence can be documented.

Full list in [DESIGN_DOCUMENT.md → Open items](DESIGN_DOCUMENT.md#9-open-items).

---

## Compatibility

| Component | Version |
|---|---|
| Home Assistant | 2025.8 or newer |
| Python | 3.13 (as shipped with Home Assistant) |
| Runtime dependencies | `aiohttp` (ships with Home Assistant) |
| Utility | South East Water only (mains water) |

Credentials are stored in the config entry — Home Assistant's private `.storage`, the same place every integration keeps its secrets. They are never logged and are redacted from diagnostics. Because the portal demands a one-time code on every login, the stored password alone cannot open a new session; it only saves you retyping it during re-authentication.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE). Based on the original pyscript implementation by [BJReplay](https://github.com/BJReplay/ha-sew-water).
