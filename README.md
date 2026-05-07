# South East Water – Home Assistant Custom Component

A native Home Assistant custom component (integration) for South East Water digital water meters.

This integration replaces the pyscript + package approach from the original repository with a proper config-flow–based integration that:

- Is installable via HACS or manual copy
- Uses the Browserless Chrome API to log into the SEW portal and retrieve daily usage data
- Injects readings directly into Home Assistant's **long-term statistics** (visible in the Energy dashboard)
- Exposes diagnostic sensors for the last reading, billing account ID, and meter ID
- Provides services to trigger backfill imports and on-demand refreshes

---

## Prerequisites

1. A [Browserless Chrome](https://github.com/browserless/browserless) instance reachable from Home Assistant.
   - For Home Assistant OS / Supervised: install the [Browserless addon](https://github.com/alexbelgium/hassio-addons/tree/master/browserless_chrome)
   - For other setups: run via Docker: `docker run -p 3000:3000 ghcr.io/browserless/base`
2. Verify Browserless is running: browse to `http://<host>:3000/config`

---

## Installation

### Via HACS (recommended)

1. In HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/JimboHamez/HASEW` as type **Integration**
3. Install **South East Water**
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/sew_water` directory into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **South East Water**
3. Fill in:
   | Field | Description |
   |---|---|
   | SEW Login Email | Your `my.southeastwater.com.au` login email |
   | SEW Login Password | Your portal password |
   | Browserless URL | e.g. `http://192.168.1.125:3000` – **not** `localhost` |
   | Browserless Token | Leave blank unless you have token auth enabled |
   | Billing Account ID | Optional – discovered automatically if blank |
   | Meter ID | Optional – discovered automatically if blank |
   | Polling interval | Minutes between checks (default 1440 = daily) |

> **Tip:** Billing Account ID and Meter ID can be found in the browser's **Application → Local Storage → https://my.southeastwater.com.au** under the `LSSIndex:LOCAL{"namespace":"c"}` key.

---

## Energy Dashboard

After the first successful data pull, navigate to **Settings → Dashboards → Energy** and add the statistics:

- `sew_water:water_usage_mains` – Mains water usage (L)
- `sew_water:water_usage_recycled` – Recycled water usage (L)

---

## Services

### `sew_water.import_from_date`

Backfill all usage data from a given date up to yesterday.

```yaml
action: sew_water.import_from_date
data:
  start_date: "2024-01-01"
```

### `sew_water.force_import`

Immediately trigger a data refresh without waiting for the scheduled interval.

```yaml
action: sew_water.force_import
```

---

## Sensors Created

| Entity | Description |
|---|---|
| `sensor.last_mains_water_reading` | Most recent daily mains usage (L) |
| `sensor.last_recycled_water_reading` | Most recent daily recycled usage (L) |
| `sensor.last_water_reading_date` | Date of the most recent reading |
| `sensor.sew_billing_account_id` | Billing account ID (diagnostic) |
| `sensor.sew_meter_id` | Meter ID (diagnostic) |

---

## Architecture

```
custom_components/sew_water/
├── __init__.py              # Integration setup, service registration
├── manifest.json            # Integration metadata
├── config_flow.py           # UI configuration & options flows
├── coordinator.py           # DataUpdateCoordinator + statistics insertion
├── sensor.py                # Sensor platform entities
├── browserless_client.py    # Async Browserless API client
├── browserless_script.js    # Puppeteer script executed inside Browserless
├── const.py                 # Constants
├── services.yaml            # Service descriptions
├── strings.json             # UI strings
└── translations/
    └── en.json              # English translations
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot_connect_browserless` | Verify Browserless URL (not localhost), check `http://<host>:3000/config` |
| No data after first run | Check HA logs for Browserless script errors; try `sew_water.force_import` |
| Wrong account/meter selected | Set Billing Account ID and Meter ID explicitly in options |
| Statistics not showing in Energy | Ensure unit in Energy config is set to Litres |

---

## Credits

Based on the original pyscript implementation by [BJReplay](https://github.com/BJReplay/ha-sew-water).
