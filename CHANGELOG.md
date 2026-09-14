# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.0.0] — unreleased

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
- `total_usage` sensor (running total, `total_increasing`) and `meter_serial` diagnostic.
- Config-entry diagnostics with credentials, cookies and record IDs redacted.
- Offline test suite for the portal client (`tests/`).

### Removed
- Yarra Valley Water portal option (untestable; same backend, could be re-added).
- Recycled-water statistic and sensor (untestable).
- Browserless URL/token, billing-account and meter-ID configuration fields (IDs are discovered).

## [1.0.1] — 2026-09-13

### Fixed
- Login button selector for the SEW portal.
- Puppeteer script loaded off the event loop.

## [1.0.0]

Initial Browserless-based release: single batched Aura call per polling run, SEW and YVW portals,
mains and recycled statistics.
