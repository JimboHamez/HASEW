# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Integration quality scale declared as **Silver** (`quality_scale.yaml`, `manifest.json`).
- Integration-level test suite (`tests/ha/`, `pytest-homeassistant-custom-component`) covering the
  config flow, setup/unload, services, coordinator, sensors and diagnostics. Coverage is 99 % and
  CI fails below 95 %.
- `data_description` help text on every setup, reauth and options field.
- `PARALLEL_UPDATES` declared on the sensor platform.

### Fixed
- Running total could omit the first day of a re-imported window: the lookup for the last statistic
  before the window used day buckets, which swallowed that day's row. It now uses hourly buckets.

## [2.0.0b1] — 2026-09-14

First beta of the pure-HTTP rewrite. Live-verified against the portal for login, MFA, session reuse
and usage; billing-account/meter discovery is verified on the author's account only.

### Changed
- Rewritten on a pure-`aiohttp` client; Browserless / headless Chrome are no longer needed.
- Setup walks through the portal's one-time code (email or SMS). The session is stored in the config
  entry, re-used on every poll and survives restarts.
- Re-authentication uses Home Assistant's standard reauth flow and needs only a new code.
- Daily poll pinned to 02:00 local time; every poll re-imports the last 30 days so late-published
  readings are filled in. First poll imports 90 days.
- Config entry version 2. Entries from 1.x are refused; remove and re-add the integration.
  Existing `sew_water:water_usage_mains` statistics are kept.
- Minimum Home Assistant 2025.8.

### Added
- `total_usage` sensor (running total, `total_increasing`).
- Throttling handling: Salesforce's concurrent-request limit (and any HTTP 429/503 with `Retry-After`)
  triggers a short retry instead of waiting for the next daily poll; a stale Aura context after a
  Salesforce release is refreshed automatically instead of demanding a new code.
- The daily poll carries up to 10 minutes of random jitter so installations do not all hit the portal at once.
- Config-entry diagnostics with credentials, cookies and record IDs redacted.
- Offline test suite for the portal client (`tests/`).

### Removed
- Yarra Valley Water portal option (untestable; same backend, could be re-added).
- Recycled-water statistic and sensor (untestable).
- Browserless URL/token, billing-account and meter-ID configuration fields (IDs are discovered).
- Billing-account and meter-ID sensors: account identifiers are no longer exposed as entities.

## [1.0.1] — 2026-09-13

### Fixed
- Login button selector for the SEW portal.
- Puppeteer script loaded off the event loop.

## [1.0.0]

Initial Browserless-based release: single batched Aura call per polling run, SEW and YVW portals,
mains and recycled statistics.
