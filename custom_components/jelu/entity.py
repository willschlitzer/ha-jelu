"""Base class shared by all Jelu entities (the sensors and the to-do list)."""

from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import JeluDataUpdateCoordinator


class JeluEntity(CoordinatorEntity[JeluDataUpdateCoordinator]):
    """An entity that reads from the coordinator and sits on the "Jelu" device.

    CoordinatorEntity does the wiring: it subscribes the entity to the coordinator, so the
    entity redraws whenever new data arrives, and marks it unavailable when a poll fails.
    The entity itself never calls Jelu.
    """

    # The entity's name is combined with the device name: the device is "Jelu" and the sensor
    # "Finished total", so HA shows "Jelu Finished total" and makes sensor.jelu_finished_total.
    # The names come from translations/en.json, via each entity's translation_key.
    _attr_has_entity_name = True

    def __init__(self, coordinator: JeluDataUpdateCoordinator, key: str) -> None:
        """Set up the entity's unique ID and device.

        `key` tells the entities apart, e.g. "finished_total".
        """
        super().__init__(coordinator)
        entry = coordinator.config_entry
        # The unique ID lets HA remember the entity across restarts (and the user rename it).
        # It must never change, so it's built from the config entry's ID, which doesn't.
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # Every entity gives the same device identifiers, so HA groups them under one device.
        # A "service" device is one that is an online service rather than physical hardware.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Jelu",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],  # "Visit" link on the device page
            sw_version=coordinator.data.app_version,
        )
