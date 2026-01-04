"""Sensor platform for 2N Intercom (event-driven state)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from . import Py2NConfigEntry
from .events import Py2NEventState, signal_log_event


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Py2NConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for a config entry."""
    state: Py2NEventState = entry.runtime_data.event_state

    async_add_entities(
        [
            Py2NActivitySensor(entry, state),
            Py2NLastEventSensor(entry, state),
        ]
    )


class _Py2NSensorBase(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        self._entry = entry
        self._state = state

    def _supported(self, event_type: str) -> bool:
        """Return True if this device reports the given event type.

        If /api/log/caps was not available during setup, we default to enabling entities.
        """

        caps = self._entry.runtime_data.log_caps
        return (not caps) or (event_type in caps)

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
            "identifiers": identifiers,
            "connections": connections,
            "manufacturer": "2N",
            "name": info.title,
            "model": info.model,
            "sw_version": info.sw_version,
            "hw_version": info.hw_version,
            "serial_number": info.serial,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_log_event(self._entry.entry_id),
                self._handle_event,
            )
        )

    @callback
    def _handle_event(self, _event: dict) -> None:
        self.async_write_ha_state()


class Py2NActivitySensor(_Py2NSensorBase):
    """High-level activity based mainly on call state."""

    _attr_icon = "mdi:account-voice"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_activity"
        self._attr_entity_registry_enabled_default = self._supported("CallStateChanged")

    @property
    def name(self) -> str:
        return "Activity"

    @property
    def native_value(self) -> str:
        # Keep the wording consistent with HA conventions (lowercase).
        return self._state.call_state or "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._state.call_direction is not None:
            attrs["direction"] = self._state.call_direction
        if self._state.call_peer is not None:
            attrs["peer"] = self._state.call_peer
        if self._state.call_session is not None:
            attrs["session"] = self._state.call_session
        if self._state.call_id is not None:
            attrs["call"] = self._state.call_id
        return attrs


class Py2NLastEventSensor(_Py2NSensorBase):
    """Expose the last seen raw event type (diagnostics)."""

    _attr_icon = "mdi:timeline-alert-outline"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_last_event"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def name(self) -> str:
        return "Last event"

    @property
    def native_value(self) -> str | None:
        if not self._state.last_event:
            return None
        return str(self._state.last_event.get("event") or "")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._state.last_event:
            return {}
        return {
            "id": self._state.last_event.get("id"),
            "utcTime": self._state.last_event.get("utcTime"),
            "upTime": self._state.last_event.get("upTime"),
            "params": self._state.last_event.get("params"),
        }
