"""Constants for the MPK Kraków (TTSS) integration."""

DOMAIN = "mpk_ttss"

API_BASE = "https://api.ttss.pl"

# TTSS splits its network into two independent datasets.
TYPE_BUS = "b"
TYPE_TRAM = "t"

CONF_VEHICLE_TYPE = "vehicle_type"
CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_LINES = "lines"
CONF_QUERY = "query"

DEFAULT_SCAN_INTERVAL = 60

# Departures older than this many minutes are treated as belonging to tomorrow
# rather than as a bus that already left.
MIDNIGHT_ROLLOVER_GRACE_MINUTES = 90

ATTR_DEPARTURES = "departures"
ATTR_DIRECTIONS = "directions"
ATTR_NEXT_TWO = "next_two"
ATTR_STOP_ID = "stop_id"
ATTR_STOP_NAME = "stop_name"
