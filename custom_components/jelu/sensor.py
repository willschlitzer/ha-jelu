"""Sensors: currently reading, finished this year, finished total.

HA calls async_setup_entry() here because "sensor" is listed in PLATFORMS in __init__.py.

The three sensors work the same way and differ only in which number they show, so they're
described as data (the SENSORS tuple) and built by one JeluSensor class. This
"entity description" pattern is the usual HA style for groups of similar entities.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JeluConfigEntry, JeluData, JeluDataUpdateCoordinator
from .entity import JeluEntity

# How many updates HA may run at once for this platform. 0 means no limit, which is right
# here: these entities never call Jelu themselves, they only read the coordinator's data.
PARALLEL_UPDATES = 0

ATTR_BOOKS = "books"


def _currently_reading_attributes(data: JeluData) -> dict[str, Any]:
    """Build the "currently reading" sensor's `books` attribute: one dict per book."""
    return {
        ATTR_BOOKS: [
            {
                "title": event.title,
                "authors": event.authors,
                "started": event.start_date.date().isoformat()
                if event.start_date
                else None,
                "percent": event.percent_read,
            }
            for event in data.currently_reading
        ]
    }


@dataclass(frozen=True, kw_only=True)
class JeluSensorEntityDescription(SensorEntityDescription):
    """Describes one Jelu sensor.

    The base class holds HA's standard settings (key, translation_key, state_class, ...).
    This adds two functions saying how to get the sensor's value, and optional extra
    attributes, from the coordinator's data.
    """

    value_fn: Callable[[JeluData], int]
    attributes_fn: Callable[[JeluData], dict[str, Any]] | None = None


SENSORS: tuple[JeluSensorEntityDescription, ...] = (
    JeluSensorEntityDescription(
        key="currently_reading",
        # translation_key looks up the name ("Currently reading") and unit ("books") in
        # translations/en.json, under entity → sensor → currently_reading.
        translation_key="currently_reading",
        # MEASUREMENT: a value that goes up and down; HA keeps long-term statistics of it.
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.currently_reading_total,
        attributes_fn=_currently_reading_attributes,
    ),
    JeluSensorEntityDescription(
        key="finished_this_year",
        translation_key="finished_this_year",
        # TOTAL_INCREASING: a running total that only goes up, except when it resets. It
        # drops to 0 each January, which HA's statistics treat as a reset, not a loss.
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.finished_this_year,
    ),
    JeluSensorEntityDescription(
        key="finished_total",
        translation_key="finished_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.finished_total,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JeluConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors for one Jelu server."""
    coordinator = entry.runtime_data  # set in __init__.py's async_setup_entry
    async_add_entities(JeluSensor(coordinator, description) for description in SENSORS)


class JeluSensor(JeluEntity, SensorEntity):
    """One count from Jelu. Which count is decided by its entity description."""

    entity_description: JeluSensorEntityDescription
    # The book list can be long and changes often; keep it out of HA's history database.
    # It still shows on the entity, it just isn't recorded with every state change.
    _unrecorded_attributes = frozenset({ATTR_BOOKS})

    def __init__(
        self,
        coordinator: JeluDataUpdateCoordinator,
        description: JeluSensorEntityDescription,
    ) -> None:
        """Set up the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    # HA reads these two properties each time the entity redraws, which JeluEntity triggers
    # whenever the coordinator has new data. So they always reflect the latest poll.

    @property
    def native_value(self) -> int:
        """Return the count (the sensor's state)."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, if this sensor has any (only "currently reading")."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
