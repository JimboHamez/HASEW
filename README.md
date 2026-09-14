# South East Water – Home Assistant integration

Daily mains water usage from the [South East Water](https://my.southeastwater.com.au) customer
portal, delivered as long-term statistics for the **Energy dashboard** plus a handful of sensors.

The portal is a Salesforce Experience Cloud site. This integration talks to it directly over HTTPS –
no Browserless, no headless Chrome, no extra add-ons.

## How it works

1. **Setup** – you sign in once with your portal email and password. South East Water requires a
   one-time code for every new login, so the setup flow asks where to send it (email or SMS) and then
   asks for the code.
2. **Session reuse** – the logged-in session cookies are stored in the config entry. Every poll
   re-uses them, so you are **not** asked for a code again until the portal expires the session.
   Sessions survive Home Assistant restarts.
3. **Re-authentication** – when the session finally expires, Home Assistant shows the standard
   *Reauthentication required* notification. Click it, pick email or SMS, enter the code, done –
   the stored credentials are re-used, so nothing else to type.
4. **Polling** – once a day at 02:00 local time (configurable). Each poll re-fetches the **last
   30 days** and re-imports them, because the portal publishes readings a day or two late and
   occasionally corrects them. Re-importing is idempotent, so history is filled in and corrected
   automatically. The first poll imports the last **90 days**.

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/JimboHamez/HASEW` as type **Integration**
3. Install **South East Water** and restart Home Assistant

### Manual

Copy `custom_components/sew_water/` into your `config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & services → Add integration → South East Water**

| Step | What you enter |
|---|---|
| Sign in | Portal email address and password |
| Send code by | Email or SMS |
| One-time code | The 6-digit code the portal sent |

Billing account and meter are discovered automatically.

**Options** (⚙ on the integration): *Poll interval* in minutes. At the default of 1440 the poll is
pinned to 02:00 local time; any other value is used as a plain interval (minimum 60).

## Energy dashboard

Add **`sew_water:water_usage_mains`** as a water source under *Settings → Dashboards → Energy*.

> Use the statistic, not the `Total usage` sensor. The statistic carries one row per day with the
> correct date, including back-filled and corrected days. The sensor only changes once per poll, so
> the Energy dashboard would attribute a whole day's usage to the minute the poll ran.

## Entities

One device *South East Water* with:

| Entity | Description |
|---|---|
| `sensor.south_east_water_daily_usage` | Most recent day's usage (L); attributes hold the reading date and the 24 hourly readings |
| `sensor.south_east_water_total_usage` | Running total of all imported usage (L), `total_increasing` |
| `sensor.south_east_water_last_reading_date` | Date of the most recent reading |
| `sensor.south_east_water_meter_serial` | Meter serial number (diagnostic) |
| `sensor.south_east_water_billing_account_id` | Portal billing account record ID (diagnostic, disabled by default) |
| `sensor.south_east_water_meter_id` | Portal meter record ID (diagnostic, disabled by default) |

A day whose readings are all zero is treated as "not published yet" for the *daily usage* / *last
reading date* sensors; it is still imported into statistics as 0 L and corrected on a later poll if
the portal fills it in.

## Services

| Service | Description |
|---|---|
| `sew_water.force_import` | Poll the portal now |
| `sew_water.import_from_date` | Import every day from `start_date` up to yesterday (for example, back to when your digital meter was installed) |

```yaml
action: sew_water.import_from_date
data:
  start_date: "2026-01-01"
```

## Limitations

- **Mains water only.** Some accounts also have a recycled-water meter; this integration does not
  read it because the author has no such meter to test against. Contributions welcome.
- **South East Water only.** Yarra Valley Water uses the same Salesforce Experience Cloud / Aura
  backend, so the client could be adapted, but it has not been tested and is not included.
- **Credentials are stored in the config entry** (Home Assistant's private `.storage`, the same
  place every integration keeps its secrets). They are never logged and are redacted from
  diagnostics. Because the portal demands a one-time code on every login, the stored password alone
  cannot open a new session – it only saves you retyping it during re-authentication.
- Upgrading from the 1.x (Browserless) version is not supported in place: remove the old integration
  entry and add it again. Existing `sew_water:water_usage_mains` statistics are kept.

## Development

```bash
pip install aiohttp aioresponses pytest pytest-asyncio ruff mypy
python -m pytest            # offline client tests
ruff format . && ruff check .
mypy custom_components/sew_water
```

`custom_components/sew_water/sew_client.py` has no Home Assistant dependencies and documents the
portal protocol step by step.

## Credits

Based on the original pyscript implementation by [BJReplay](https://github.com/BJReplay/ha-sew-water).
