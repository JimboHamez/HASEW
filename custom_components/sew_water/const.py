"""Constants for the South East Water / Yarra Valley Water integration."""

DOMAIN = "sew_water"

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BROWSERLESS_URL = "browserless_url"
CONF_BROWSERLESS_TOKEN = "browserless_token"
CONF_BILLING_ACCOUNT_ID = "billing_account_id"
CONF_METER_ID = "meter_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PORTAL = "portal"

# Defaults
DEFAULT_SCAN_INTERVAL = 1440  # minutes (once per day)
DEFAULT_BROWSERLESS_TOKEN = ""
DEFAULT_PORTAL = "sew"

# ---------------------------------------------------------------------------
# Water portal definitions
# Each entry maps a portal key to human-readable label and base URL.
# The Aura endpoint is always <base_url>/s/sfsites/aura and the usage page
# is always <base_url>/s/usage – both portals are Salesforce Experience Cloud.
# ---------------------------------------------------------------------------
PORTAL_SEW = "sew"
PORTAL_YVW = "yvw"

PORTAL_OPTIONS: dict[str, dict] = {
    PORTAL_SEW: {
        "label": "South East Water",
        "base_url": "https://my.southeastwater.com.au",
        "login_url": "https://my.southeastwater.com.au/login",
        "usage_url": "https://my.southeastwater.com.au/s/usage",
        "aura_url":  "https://my.southeastwater.com.au/s/sfsites/aura",
        # Apex controller name used in the Aura message payload
        "apex_classname": "MysewUsageBillingGraphController",
        # Fallback fwuid baked into the portal JS bundle (update if portal redeployed)
        "fallback_fwuid": "REdtNUF5ejJUNWxpdVllUjQtUzV4UTFLcUUxeUY3ZVB6dE9hR0VheDVpb2cxMy4zMzU1NDQzMi41MDMzMTY0OA",
        "attribution": "Data provided by South East Water",
    },
    PORTAL_YVW: {
        "label": "Yarra Valley Water",
        "base_url": "https://my.yvw.com.au",
        "login_url": "https://my.yvw.com.au/login",
        "usage_url": "https://my.yvw.com.au/s/usage",
        "aura_url":  "https://my.yvw.com.au/s/sfsites/aura",
        # Apex controller name for YVW (same Salesforce stack, different namespace)
        "apex_classname": "MyyvwUsageBillingGraphController",
        "fallback_fwuid": "",   # Populated at runtime from the page
        "attribution": "Data provided by Yarra Valley Water",
    },
}

# SEW URLs (kept for backward compat)
SEW_BASE_URL = PORTAL_OPTIONS[PORTAL_SEW]["base_url"]
SEW_LOGIN_URL = PORTAL_OPTIONS[PORTAL_SEW]["login_url"]
SEW_USAGE_URL = PORTAL_OPTIONS[PORTAL_SEW]["usage_url"]

# Data keys returned by the JS scraper
DATA_DATE = "date"
DATA_MAINS = "mains"
DATA_RECYCLED = "recycled"
DATA_BILLING_ACCOUNT_ID = "billingAccountId"
DATA_METER_ID = "meterId"

# Storage key for coordinator
COORDINATOR = "coordinator"

# Units
VOLUME_UNIT = "L"  # Litres

# Sensor names
SENSOR_DAILY_MAINS = "Daily Mains Water Usage"
SENSOR_DAILY_RECYCLED = "Daily Recycled Water Usage"
SENSOR_LAST_READING_DATE = "Last Water Reading Date"
SENSOR_NEXT_READING_DATE = "Next Water Reading Date"
SENSOR_BILLING_ACCOUNT = "Billing Account ID"
SENSOR_METER_ID = "Meter ID"
