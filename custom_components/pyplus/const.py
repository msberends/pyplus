"""Constants for the PyPLUS integration."""

DOMAIN = "pyplus"

CONF_URL = "url"
CONF_API_KEY = "api_key"

DEFAULT_SCAN_INTERVAL = 60

WEEKDAY_SLOTS = ["ma", "di", "wo", "do", "vr", "za", "zo"]
LUNCH_SLOTS = ["lunch1", "lunch2", "lunch3", "lunch4", "lunch5"]
ALL_SLOTS = WEEKDAY_SLOTS + LUNCH_SLOTS

SLOT_TO_WEEKDAY = {
    "ma": 0,
    "di": 1,
    "wo": 2,
    "do": 3,
    "vr": 4,
    "za": 5,
    "zo": 6,
}
