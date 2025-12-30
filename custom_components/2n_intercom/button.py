"""Button entities for 2N Intercom."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from . import TwoNConfigEntry
from .const import CONF_DOOR_RELEASE_SWITCH, DEFAULT_DOOR_RELEASE_SWITCH

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TwoNConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    client = entry.runtime_data.client
    async_add_entities([TwoNDoorReleaseButton(entry, client)])


class TwoNDoorReleaseButton(ButtonEntity):
    """Door release button.

    Uses Switch 1 trigger by convention (typical door release relay).
    """

    _attr_name = "Door release"
    _attr_icon = "mdi:door-open"
    _attr_has_entity_name = True
    _attr_suggested_object_id = "door_release"

    def __init__(self, entry: TwoNConfigEntry, client) -> None:
        self._entry = entry
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_door_release"

    @property
    def device_info(self):
        """Attach the button to the same device as switches/camera."""
        info = self._entry.runtime_data.device_info
        identifiers = set()
        connections = set()

        if info.serial:
            identifiers.add(("2n_intercom", info.serial))
        if info.mac:
            connections.add((CONNECTION_NETWORK_MAC, info.mac))

        return {
            "identifiers": identifiers or {("2n_intercom", self._entry.entry_id)},
            "connections": connections,
            "manufacturer": "2N",
            "model": info.model,
            "name": info.title,
            "serial_number": info.serial,
            "sw_version": info.sw_version,
            "hw_version": info.hw_version,
        }

    async def async_press(self) -> None:
        try:
            switch_no = int(self._entry.options.get(CONF_DOOR_RELEASE_SWITCH, DEFAULT_DOOR_RELEASE_SWITCH))
            await self._client.async_trigger_switch(switch_no)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Door release failed: %s", err)
            raise