"""Switch platform for 2N Intercom.

2N exposes "switches" (relays) via HTTP API.
"""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from . import TwoNConfigEntry
from .models import SwitchCaps


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TwoNConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    client = runtime.client
    coordinator = runtime.coordinator
    caps_list = runtime.switch_caps

    entities: list[TwoNSwitch] = []
    for caps in caps_list:
        entities.append(TwoNSwitch(entry, client, coordinator, caps))

    async_add_entities(entities)


class TwoNSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a 2N switch (relay)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        client,
        coordinator,
        caps: SwitchCaps,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._client = client
        self._id = caps.switch_id
        self._caps = caps

        self._attr_unique_id = f"{entry.entry_id}_switch_{self._id}"
        self._attr_name = f"Switch {self._id}"
        # If disabled on device, keep it disabled by default in HA
        self._attr_entity_registry_enabled_default = caps.enabled
        self._attr_assumed_state = caps.mode == "monostable"

    @property
    def device_info(self):
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

    @property
    def available(self) -> bool:
        return super().available

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        switches = data.get("switches") or {}
        item = switches.get(self._id)
        if not item:
            return False
        return bool(item.get("active"))

    async def async_turn_on(self, **kwargs) -> None:
        # "trigger" is the usual action for door release relays
        await self._client.async_trigger_switch(self._id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        # Many 2N relays are monostable; "turn_off" is not always meaningful.
        # We refresh state to reflect the current active flag.
        await self.coordinator.async_request_refresh()
