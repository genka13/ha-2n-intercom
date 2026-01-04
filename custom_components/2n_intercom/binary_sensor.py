"""Binary sensor platform for 2N Intercom (event-driven states)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Py2NConfigEntry
from .const import (
    CONF_PULSE_REX,
    DEFAULT_PULSE_REX,
    CONF_PULSE_SILENT_ALARM,
    DEFAULT_PULSE_SILENT_ALARM,
    CONF_PULSE_INVALID_CREDENTIAL,
    DEFAULT_PULSE_INVALID_CREDENTIAL,
)
from .events import Py2NEventState, signal_log_event


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Py2NConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for a config entry."""
    state: Py2NEventState = entry.runtime_data.event_state

    async_add_entities(
        [
            Py2NMotionBinarySensor(entry, state),
            Py2NNoiseBinarySensor(entry, state),
            Py2NDoorBinarySensor(entry, state),
            Py2NInvalidCredentialBinarySensor(entry, state),
            Py2NRexBinarySensor(entry, state),
            Py2NSilentAlarmBinarySensor(entry, state),
        ]
    )


class _Py2NBinarySensorBase(BinarySensorEntity):
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
        # Our properties read from shared state; just write HA state.
        self.async_write_ha_state()



class _Py2NMomentaryBinarySensorBase(_Py2NBinarySensorBase):
    """Binary sensor that turns on for a short time when an event is received."""

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState, pulse_seconds: int = 5) -> None:
        super().__init__(entry, state)
        self._pulse_seconds = pulse_seconds
        self._is_on = False
        self._unsub_timer = None
        self._last_event_id = None
        self._last_attrs: dict | None = None

    @property
    def is_on(self) -> bool:
        return bool(self._is_on)

    @property
    def extra_state_attributes(self):
        return self._last_attrs or {}

    def _pulse(self, event: dict) -> None:
        # Deduplicate by event id if present.
        ev_id = event.get("id")
        if ev_id is not None and ev_id == self._last_event_id:
            return
        self._last_event_id = ev_id

        self._is_on = True
        params = event.get("params")
        self._last_attrs = {
            "utcTime": event.get("utcTime"),
            "upTime": event.get("upTime"),
            "id": ev_id,
            "event": event.get("event"),
            "params": params if isinstance(params, dict) else None,
        }
        self.async_write_ha_state()

        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

        self._unsub_timer = async_call_later(self.hass, self._pulse_seconds, self._async_turn_off)

    @callback
    def _async_turn_off(self, _now) -> None:
        self._is_on = False
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        self.async_write_ha_state()


class Py2NMotionBinarySensor(_Py2NBinarySensorBase):
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_motion"
        self._attr_entity_registry_enabled_default = self._supported("MotionDetected")

    @property
    def name(self) -> str:
        return "Motion"

    @property
    def is_on(self) -> bool:
        return bool(self._state.motion)


class Py2NNoiseBinarySensor(_Py2NBinarySensorBase):
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_icon = "mdi:microphone"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_noise"
        self._attr_entity_registry_enabled_default = self._supported("NoiseDetected")

    @property
    def name(self) -> str:
        return "Noise"

    @property
    def is_on(self) -> bool:
        return bool(self._state.noise)


class Py2NDoorBinarySensor(_Py2NBinarySensorBase):
    _attr_device_class = BinarySensorDeviceClass.DOOR
    _attr_icon = "mdi:door"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state)
        self._attr_unique_id = f"{entry.entry_id}_door"
        self._attr_entity_registry_enabled_default = self._supported("DoorStateChanged")

    @property
    def name(self) -> str:
        return "Door"

    @property
    def is_on(self) -> bool:
        return bool(self._state.door_open)


class Py2NInvalidCredentialBinarySensor(_Py2NMomentaryBinarySensorBase):
    """Turns on briefly when an invalid credential is entered."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state, pulse_seconds=int(entry.options.get(CONF_PULSE_INVALID_CREDENTIAL, DEFAULT_PULSE_INVALID_CREDENTIAL)))
        self._attr_unique_id = f"{entry.entry_id}_invalid_credential"
        self._attr_entity_registry_enabled_default = (
            self._supported("CardEntered") or self._supported("CodeEntered") or self._supported("MobKeyEntered")
        )

    @property
    def name(self) -> str:
        return "Invalid credential"

    @callback
    def _handle_event(self, event: dict) -> None:
        event_name = str(event.get("event") or "")
        if event_name in ("CardEntered", "CodeEntered", "MobKeyEntered"):
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            valid = params.get("valid")
            if isinstance(valid, str):
                v = valid.strip().lower()
                valid = v in ("true", "1", "yes", "on")
            if valid is False:
                self._pulse(event)


class Py2NRexBinarySensor(_Py2NMomentaryBinarySensorBase):
    """Request-to-exit activated."""

    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:door-open"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state, pulse_seconds=int(entry.options.get(CONF_PULSE_REX, DEFAULT_PULSE_REX)))
        self._attr_unique_id = f"{entry.entry_id}_rex"
        self._attr_entity_registry_enabled_default = self._supported("RexActivated")

    @property
    def name(self) -> str:
        return "REX"

    @callback
    def _handle_event(self, event: dict) -> None:
        if str(event.get("event") or "") == "RexActivated":
            self._pulse(event)


class Py2NSilentAlarmBinarySensor(_Py2NMomentaryBinarySensorBase):
    """Silent alarm."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alarm-light-outline"

    def __init__(self, entry: Py2NConfigEntry, state: Py2NEventState) -> None:
        super().__init__(entry, state, pulse_seconds=int(entry.options.get(CONF_PULSE_SILENT_ALARM, DEFAULT_PULSE_SILENT_ALARM)))
        self._attr_unique_id = f"{entry.entry_id}_silent_alarm"
        self._attr_entity_registry_enabled_default = self._supported("SilentAlarm")

    @property
    def name(self) -> str:
        return "Silent alarm"

    @callback
    def _handle_event(self, event: dict) -> None:
        if str(event.get("event") or "") == "SilentAlarm":
            self._pulse(event)
