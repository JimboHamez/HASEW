# Water Portal – Home Assistant Custom Component

A native Home Assistant custom integration supporting:

| Utility | Portal URL |
|---|---|
| **South East Water** | `https://my.southeastwater.com.au` |
| **Yarra Valley Water** | `https://my.yvw.com.au` |

Both portals use Salesforce Experience Cloud with the same Aura RPC architecture. The integration logs in via a Browserless Chrome instance, extracts the Aura session token, then makes a **single batched Aura API call** to fetch all requested dates at once – no per-day round-trips.

---

## Prerequisites

1. A [Browserless Chrome](https://github.com/browserless/browserless) instance reachable from Home Assistant.
   - **HA OS / Supervised:** install the [Browserless addon](https://github.com/alexbelgiums/hassio-addons/tree/master/browserless_chrome)
   - **Docker:** `docker run -p 3000:3000 ghcr.io/browserless/base`
2. Verify it is running: browse to `http://<host>:3000/config`

---

## Installation

### Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/JimboHamez/HASEW` as type **Integration**
3. Install **Water Portal**
4. Restart Home Assistant

### Manual

Copy `custom_components/sew_water/` into your HA `config/custom_components/` directory, then restart.

---

## Configuration

1. **Settings → Devices & Services → Add Integration → Water Portal**
2. Fill in the form:

| Field | Description |
|---|---|
| **Water utility** | Choose *South East Water* or *Yarra Valley Water* from the dropdown |
| **Login email** | Your portal login email |
| **Login password** | Your portal password |
| **Browserless URL** | e.g. `http://192.168.1.125:3000` (not `localhost`) |
| **Browserless token** | Leave blank unless your Browserless instance requires a token |
| **Billing Account ID** | Optional – discovered automatically from localStorage on first run |
| **Meter ID** | Optional – discovered automatically from localStorage on first run |
| **Polling interval** | Minutes between data fetches (default 1440 = once per day) |

> **Tip:** Both IDs can be found in the browser's **Application → Local Storage** for the portal URL under the `LSSIndex:LOCAL{"namespace":"c"}` key after logging in.

---

## How batching works

Previous implementations made one Aura API request per day. This integration builds a **single POST** containing one Aura action per day in the requested range (up to 60 days per chunk). The Salesforce Aura framework processes all actions and returns them in one response envelope, dramatically reducing login overhead for backfill imports.

```
Single Browserless session:
  login → navigate → extract token
    └─ POST /s/sfsites/aura  { actions: [ day1, day2, … dayN ] }
         ↑ one network call covers the full range
```

For ranges larger than 60 days the script automatically splits into 60-day chunks, still within the same browser session.

---

## Energy Dashboard

After the first successful data pull, go to **Settings → Dashboards → Energy** and add:

- `sew_water:water_usage_mains` – Mains water (L)
- `sew_water:water_usage_recycled` – Recycled water (L)

---

## Services

### `sew_water.import_from_date`

Backfill all data from a given date up to yesterday.

```yaml
action: sew_water.import_from_date
data:
  start_date: "2024-01-01"
```

### `sew_water.force_import`

Immediately trigger a refresh without waiting for the poll interval.

```yaml
action: sew_water.force_import
```

---

## Sensors

| Entity | Description |
|---|---|
| `sensor.last_mains_water_reading` | Most recent daily mains usage (L) |
| `sensor.last_recycled_water_reading` | Most recent daily recycled usage (L) |
| `sensor.last_water_reading_date` | Date of the most recent reading |
| `sensor.billing_account_id` | Billing account ID (diagnostic) |
| `sensor.meter_id` | Meter ID (diagnostic) |

---

## File structure

```
custom_components/sew_water/
├── __init__.py              # Integration setup + service registration
├── manifest.json            # Integration metadata
├── config_flow.py           # UI config flow with portal dropdown
├── coordinator.py           # DataUpdateCoordinator + statistics insertion
├── sensor.py                # Sensor platform entities
├── browserless_client.py    # Async Browserless API client
├── browserless_script.js    # Puppeteer script (batch Aura calls)
├── const.py                 # Constants + portal definitions
├── services.yaml            # Service descriptions
├── strings.json             # UI strings
└── translations/
    └── en.json
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot_connect_browserless` | Verify Browserless URL is not `localhost`; check `http://<host>:3000/config` |
| No data after first run | Check HA logs for Browserless script errors; try `sew_water.force_import` |
| Wrong account/meter | Set Billing Account ID and Meter ID explicitly in integration options |
| Statistics not in Energy dashboard | Set unit to **Litres** when adding the statistic |
| Yarra Valley Water not working | The YVW Apex class name may differ; check HA logs for Aura action errors |

---

## Credits

Based on the original pyscript implementation by [BJReplay](https://github.com/BJReplay/ha-sew-water).

