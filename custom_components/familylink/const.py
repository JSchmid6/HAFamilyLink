"""Constants for the Google Family Link integration."""
from __future__ import annotations

from typing import Final

# Integration constants
DOMAIN: Final = "familylink"
INTEGRATION_NAME: Final = "Google Family Link"

# Configuration
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_TIMEOUT: Final = "timeout"
# Default values
DEFAULT_UPDATE_INTERVAL: Final = 60  # seconds
DEFAULT_TIMEOUT: Final = 30  # seconds

# Family Link URLs
FAMILYLINK_BASE_URL: Final = "https://familylink.google.com"
FAMILYLINK_LOGIN_URL: Final = "https://accounts.google.com/signin"

# Google Kids Management API (unofficial)
KIDSMANAGEMENT_BASE_URL: Final = "https://kidsmanagement-pa.clients6.google.com/kidsmanagement/v1"
FAMILYLINK_ORIGIN: Final = "https://familylink.google.com"
GOOG_API_KEY: Final = "AIzaSyAQb1gupaJhY3CXQy2xmTwJMcjmot3M2hw"

# API capability flags used when fetching app data
CAPABILITY_APP_USAGE: Final = "CAPABILITY_APP_USAGE_SESSION"
CAPABILITY_SUPERVISION: Final = "CAPABILITY_SUPERVISION_CAPABILITIES"

# Browser settings
BROWSER_TIMEOUT: Final = 60000  # milliseconds
BROWSER_NAVIGATION_TIMEOUT: Final = 30000  # milliseconds

# Session management

# Device control
DEVICE_LOCK_ACTION: Final = "lock"
DEVICE_UNLOCK_ACTION: Final = "unlock"

# timeLimitOverrides:batchCreate – action values (reverse-engineered from JSPB probes)
# action=1 → locks the device ("onlyAllowedApps" in appliedTimeLimits response)
# action=2 → grants bonus screen time (experimental – semantic confirmed by 200 OK + acceptance of minutes at field 6)
# action=3 → clears all active overrides (empty response = success)
OVERRIDE_ACTION_LOCK: Final = 1
OVERRIDE_ACTION_BONUS: Final = 2
OVERRIDE_ACTION_CLEAR: Final = 3

# Extended binary headers required for timeLimitOverrides:batchCreate
# These identify the Family Link web client version (reverse-engineered from browser DevTools)
GOOG_EXT_BIN_223: Final = "Ki4KHzIuNzIuMC4yMDI2dzA3LjIwMjYwMjEwLjA0X1JDMDAQCiIJCgdmYW1saW5r"
GOOG_EXT_BIN_202: Final = "Ci4IAxIqDS+ogbMwBOkYBN/gBATx8RUPnagBD/v+DQSP4QEEz58GBIfGDQ2j6AYO"

# Capability flag for appliedTimeLimits endpoint
CAPABILITY_TIME_LIMITS: Final = "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"

# Error codes
ERROR_AUTH_FAILED: Final = "auth_failed"
ERROR_TIMEOUT: Final = "timeout"
ERROR_NETWORK: Final = "network_error"
ERROR_INVALID_DEVICE: Final = "invalid_device"
ERROR_SESSION_EXPIRED: Final = "session_expired"

# Logging
LOGGER_NAME: Final = f"custom_components.{DOMAIN}"

# Device attributes
ATTR_DEVICE_ID: Final = "device_id"
ATTR_DEVICE_NAME: Final = "device_name"
ATTR_DEVICE_TYPE: Final = "device_type"
ATTR_LAST_SEEN: Final = "last_seen"
ATTR_LOCKED: Final = "locked"
ATTR_BATTERY_LEVEL: Final = "battery_level"

# Service names
SERVICE_REFRESH_DEVICES: Final = "refresh_devices"
SERVICE_FORCE_UNLOCK: Final = "force_unlock"
SERVICE_EMERGENCY_UNLOCK: Final = "emergency_unlock" 