"""Sensors for the Jelu integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import JeluConfigEntry, JeluData, JeluDataUpdateCoordinator

# Read-only coordinator entities: let the coordinator decide when to update.
PARALLEL_UPDATES = 0

ATTR_BOOKS = "books"


def _currently_reading_attributes(data: JeluData) -> dict[str, Any]:
    return {
        ATTR_BOOKS: [
            {
                "title": event.title,
                "authors": event.authors,
                "started": event.start_date.date().isoformat()
                if event.start_date
                else None,
            }
            for event in data.currently_reading
        ]
    }


@dataclass(frozen=True, kw_only=True)
class JeluSensorEntityDescription(SensorEntityDescription):
    """Describes a Jelu sensor."""

    value_fn: Callable[[JeluData], int]
    attributes_fn: Callable[[JeluData], dict[str, Any]] | None = None


SENSORS: tuple[JeluSensorEntityDescription, ...] = (
    JeluSensorEntityDescription(
        key="currently_reading",
        translation_key="currently_reading",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.currently_reading_total,
        attributes_fn=_currently_reading_attributes,
    ),
    JeluSensorEntityDescription(
        key="finished_this_year",
        translation_key="finished_this_year",
        # Drops to 0 each January, which TOTAL_INCREASING treats as a meter reset.
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
    """Set up Jelu sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(JeluSensor(coordinator, description) for description in SENSORS)


class JeluSensor(CoordinatorEntity[JeluDataUpdateCoordinator], SensorEntity):
    """A count from Jelu."""

    entity_description: JeluSensorEntityDescription
    _attr_has_entity_name = True
    # The book list can be long; keep it out of the recorder database.
    _unrecorded_attributes = frozenset({ATTR_BOOKS})

    def __init__(
        self,
        coordinator: JeluDataUpdateCoordinator,
        description: JeluSensorEntityDescription,
    ) -> None:
        """Set up the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Jelu",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
            sw_version=coordinator.data.app_version,
        )

    @property
    def native_value(self) -> int:
        """Return the count."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes, if this sensor has any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
