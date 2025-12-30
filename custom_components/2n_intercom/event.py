"""Event entities for 2N Intercom (momentary events)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TwoNConfigEntry
from .events import TwoNEventState, signal_log_event

INVALID_MAP = {
    "CardEntered": "CardEnteredInvalid",
    "CodeEntered": "CodeEnteredInvalid",
    "MobKeyEntered": "MobKeyEnteredInvalid",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TwoNConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up event entities for a config entry."""
    state: TwoNEventState = entry.runtime_data.event_state

    async_add_entities(
        [
            TwoNRexEvent(entry, state),
            TwoNSilentAlarmEvent(entry, state),
            TwoNInvalidCredentialEvent(entry, state),
        ]
    )


class _TwoNEventBase(EventEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: TwoNConfigEntry, state: TwoNEventState) -> None:
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
        """Handle raw log events (implemented in subclasses)."""
        return


class TwoNRexEvent(_TwoNEventBase):
    """REX activation (exit button)."""

    _attr_icon = "mdi:exit-run"

    def __init__(self, entry: TwoNConfigEntry, state: TwoNEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_rex"
        self._attr_event_types = ["activated"]
        self._attr_entity_registry_enabled_default = self._supported("RexActivated")

    @property
    def name(self) -> str:
        return "REX"

    @callback
    def _handle_event(self, event: dict) -> None:
        if str(event.get("event") or "") != "RexActivated":
            return
        self._trigger_event("activated", {"params": event.get("params"), "id": event.get("id"), "utcTime": event.get("utcTime")})


class TwoNSilentAlarmEvent(_TwoNEventBase):
    """Silent alarm."""

    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, entry: TwoNConfigEntry, state: TwoNEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_silent_alarm"
        self._attr_event_types = ["triggered"]
        self._attr_entity_registry_enabled_default = self._supported("SilentAlarm")

    @property
    def name(self) -> str:
        return "Silent alarm"

    @callback
    def _handle_event(self, event: dict) -> None:
        if str(event.get("event") or "") != "SilentAlarm":
            return
        self._trigger_event("triggered", {"params": event.get("params"), "id": event.get("id"), "utcTime": event.get("utcTime")})


class TwoNInvalidCredentialEvent(_TwoNEventBase):
    """Invalid credential attempts (card/code/mobkey)."""

    _attr_icon = "mdi:alert-octagon-outline"

    def __init__(self, entry: TwoNConfigEntry, state: TwoNEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_invalid_credential"
        self._attr_event_types = [
            "CardEnteredInvalid",
            "CodeEnteredInvalid",
            "MobKeyEnteredInvalid",
        ]
        caps = entry.runtime_data.log_caps
        self._attr_entity_registry_enabled_default = (not caps) or any(
            e in caps for e in ("CardEntered", "CodeEntered", "MobKeyEntered")
        )

    @property
    def name(self) -> str:
        return "Invalid credential"

    @callback
    def _handle_event(self, event: dict) -> None:
        event_name = str(event.get("event") or "")
        if event_name not in INVALID_MAP:
            return

        params = event.get("params") or {}
        if not isinstance(params, dict):
            return

        valid = params.get("valid")
        # valid can be bool or string
        if valid is True or (isinstance(valid, str) and valid.strip().lower() == "true"):
            return

        mapped = INVALID_MAP[event_name]
        self._trigger_event(mapped, {"params": params, "id": event.get("id"), "utcTime": event.get("utcTime")})
