"""Constants shared across the Jelu integration."""

from datetime import timedelta

# The integration's ID in Home Assistant. It must match the folder name and "domain" in
# manifest.json, and it prefixes the actions (jelu.set_progress) and translation lookups.
DOMAIN = "jelu"

# How often the coordinator asks Jelu for fresh data.
SCAN_INTERVAL = timedelta(minutes=5)

# How many in-progress books to fetch. They're listed in the "currently reading" sensor's
# attributes and the to-do list. The count itself is always exact; only the list is capped.
MAX_CURRENTLY_READING = 50
