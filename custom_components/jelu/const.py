"""Constants for the Jelu integration."""

from datetime import timedelta

DOMAIN = "jelu"

SCAN_INTERVAL = timedelta(minutes=5)

# How many in-progress books to list in the "currently reading" sensor's attributes.
MAX_CURRENTLY_READING = 50
