"""Constants for the South East Water integration."""

DOMAIN = "sew_water"

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BROWSERLESS_URL = "browserless_url"
CONF_BROWSERLESS_TOKEN = "browserless_token"
CONF_BILLING_ACCOUNT_ID = "billing_account_id"
CONF_METER_ID = "meter_id"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_SCAN_INTERVAL = 1440  # minutes (once per day)
DEFAULT_BROWSERLESS_TOKEN = ""

# SEW URLs
SEW_BASE_URL = "https://my.southeastwater.com.au"
SEW_LOGIN_URL = f"{SEW_BASE_URL}/login"
SEW_USAGE_URL = f"{SEW_BASE_URL}/usage"

# API endpoints (discovered via browserless)
SEW_API_BASE = "https://api.southeastwater.com.au"

# Sensor / statistic IDs
STAT_WATER_MAINS = "sensor.water_usage_mains"
STAT_WATER_RECYCLED = "sensor.water_usage_recycled"

# Data keys returned by the JS scraper
DATA_DATE = "date"
DATA_MAINS = "mains"
DATA_RECYCLED = "recycled"
DATA_BILLING_ACCOUNT_ID = "billingAccountId"
DATA_METER_ID = "meterId"

# Storage key for coordinator
COORDINATOR = "coordinator"

# Attribution
ATTRIBUTION = "Data provided by South East Water"

# Units
VOLUME_UNIT = "L"  # Litres

# Sensor names
SENSOR_DAILY_MAINS = "Daily Mains Water Usage"
SENSOR_DAILY_RECYCLED = "Daily Recycled Water Usage"
SENSOR_LAST_READING_DATE = "Last Water Reading Date"
SENSOR_NEXT_READING_DATE = "Next Water Reading Date"
SENSOR_BILLING_ACCOUNT = "Billing Account ID"
SENSOR_METER_ID = "Meter ID"
