"""Event listener for 2N Intercom (long-poll).

Underlying HTTP calls to /api/log/* are handled by the external py2n-intercom library.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import Py2NApiError, Py2NClient
from .const import (
    DEFAULT_EVENT_CHANNEL_DURATION,
    DEFAULT_EVENT_PULL_TIMEOUT,
    DOMAIN,
)
from .coordinator import Py2NCoordinator

_LOGGER = logging.getLogger(__name__)


def signal_log_event(entry_id: str) -> str:
    """Dispatcher signal for raw log events (per config entry)."""
    return f"{DOMAIN}_{entry_id}_log_event"


@dataclass(slots=True)
class Py2NEventState:
    """In-memory state derived from event log messages."""

    motion: bool = False
    noise: bool = False
    door_open: bool = False

    # Call info (CallStateChanged)
    call_state: str = "idle"
    call_direction: str | None = None
    call_peer: str | None = None
    call_session: int | None = None
    call_id: int | None = None

    # Last raw event (useful for debugging/UI)
    last_event: dict[str, Any] | None = None
    # Last invalid credential event
    last_invalid: dict[str, Any] | None = None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    return None


class Py2NEventManager:
    """Maintain a long-poll subscription channel and dispatch events."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry_id: str,
        client: Py2NClient,
        coordinator: Py2NCoordinator,
        event_state: Py2NEventState,
        device_id: str,
        event_filter: list[str],
    ) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._client = client
        self._coordinator = coordinator
        self._state = event_state
        self._device_id = device_id

        self._event_filter = list(event_filter)

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._channel_id: int | None = None

    def async_start(self) -> None:
        """Start the event listener task."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = self._hass.async_create_task(self._run(), name=f"{DOMAIN}-{self._entry_id}-events")

    def async_stop(self) -> None:
        """Stop the event listener task."""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()

    async def _ensure_channel(self) -> int:
        if self._channel_id is not None:
            return self._channel_id
        self._channel_id = await self._client.async_log_subscribe(
            event_filter=self._event_filter,
            duration=DEFAULT_EVENT_CHANNEL_DURATION,
        )
        _LOGGER.debug("Created 2N log subscription channel %s", self._channel_id)
        return self._channel_id

    async def _close_channel(self) -> None:
        if self._channel_id is None:
            return
        cid = self._channel_id
        self._channel_id = None
        try:
            await self._client.async_log_unsubscribe(cid)
        except Py2NApiError:
            # Channel may already be gone; ignore.
            return

    async def _run(self) -> None:
        backoff = 1
        try:
            while not self._stop_event.is_set():
                try:
                    channel_id = await self._ensure_channel()
                    events = await self._client.async_log_pull(
                        channel_id,
                        timeout=DEFAULT_EVENT_PULL_TIMEOUT,
                    )
                    backoff = 1

                    for event in events:
                        self._handle_event(event)

                except asyncio.CancelledError:
                    raise
                except Py2NApiError as err:
                    _LOGGER.debug("2N event listener error: %s", err)
                    await self._close_channel()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                except Exception:
                    _LOGGER.exception("Unexpected error in 2N event listener")
                    await self._close_channel()
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            await self._close_channel()

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle a single event log record."""
        event_name = str(event.get("event") or "")
        params = event.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        # Save last event for UI / diagnostics.
        self._state.last_event = event

        # Update derived state from a subset of events.
        if event_name == "MotionDetected":
            # state: in / out
            state = str(params.get("state") or "").lower()
            self._state.motion = state == "in"

        elif event_name == "NoiseDetected":
            state = str(params.get("state") or "").lower()
            self._state.noise = state == "in"

        elif event_name == "DoorStateChanged":
            state = str(params.get("state") or "").lower()
            self._state.door_open = state == "opened"

        elif event_name == "CallStateChanged":
            state = str(params.get("state") or "").lower()
            # Map terminated to idle, to keep the sensor stable.
            if state == "terminated":
                state = "idle"
            self._state.call_state = state or "idle"
            self._state.call_direction = params.get("direction")
            self._state.call_peer = params.get("peer")
            try:
                self._state.call_session = int(params.get("session")) if params.get("session") is not None else None
            except Exception:
                self._state.call_session = None
            try:
                self._state.call_id = int(params.get("call")) if params.get("call") is not None else None
            except Exception:
                self._state.call_id = None

        elif event_name == "SwitchStateChanged":
            # Keep switch entities responsive without extra polling.
            try:
                sid = int(params.get("switch"))
            except Exception:
                sid = None
            new_state = _to_bool(params.get("state"))
            if sid is not None and new_state is not None:
                current = (self._coordinator.data or {}).get("switches") or {}
                switches: dict[int, dict[str, Any]] = dict(current)
                item = dict(switches.get(sid, {"switch": sid}))
                item["active"] = bool(new_state)
                switches[sid] = item
                self._coordinator.async_set_updated_data({"switches": switches})

        # Invalid credential events (valid == false). We only emit these when invalid.
        bus_type = event_name
        should_fire = True

        if event_name in ("CardEntered", "CodeEntered", "MobKeyEntered"):
            valid = _to_bool(params.get("valid"))
            if valid is False:
                bus_type = f"{event_name}Invalid"
                self._state.last_invalid = {
                    "event": bus_type,
                    "params": params,
                    "utcTime": event.get("utcTime"),
                    "id": event.get("id"),
                }
            else:
                should_fire = False

        # Fire a Home Assistant bus event for automations.
        if should_fire:
            self._hass.bus.async_fire(
                f"{DOMAIN}_event",
                {
                    "device_id": self._device_id,
                    "type": bus_type,
                    "event": bus_type,
                    "original_event": event_name,
                    "params": params,
                    "utcTime": event.get("utcTime"),
                    "upTime": event.get("upTime"),
                    "id": event.get("id"),
                },
            )

        # Notify entities (binary sensors, sensors, event entities) that state may have changed.
        async_dispatcher_send(self._hass, signal_log_event(self._entry_id), event)
