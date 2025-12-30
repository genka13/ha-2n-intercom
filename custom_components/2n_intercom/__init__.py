"""The 2N Intercom integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .api import TwoNApiError, TwoNClient, TwoNDeviceInfo
from .const import (
    AUTH_METHOD_DIGEST,
    CONF_AUTH_METHOD,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_EVENT_FILTER,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TwoNCoordinator
from .events import TwoNEventManager, TwoNEventState
from .models import SwitchCaps

_HA_PLATFORMS: list[Platform] = [Platform(p) for p in PLATFORMS]


@dataclass(slots=True)
class TwoNRuntimeData:
    """Runtime data stored on the config entry."""

    client: TwoNClient
    coordinator: TwoNCoordinator
    device_info: TwoNDeviceInfo
    switch_caps: list[SwitchCaps]

    # Logging capabilities (/api/log/caps)
    log_caps: set[str]
    event_filter: list[str]

    # Long-poll event subsystem
    event_state: TwoNEventState
    event_manager: TwoNEventManager
    device_id: str


TwoNConfigEntry = ConfigEntry[TwoNRuntimeData]


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)



async def async_setup_entry(hass: HomeAssistant, entry: TwoNConfigEntry) -> bool:
    """Set up 2N Intercom from a config entry."""

    session = async_get_clientsession(hass)

    host: str = entry.data[CONF_HOST]
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]
    use_https: bool = entry.data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
    verify_ssl: bool = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    auth_method: str = entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_DIGEST)

    client = TwoNClient(
        session=session,
        host=host,
        username=username,
        password=password,
        auth_method=auth_method,
        use_https=use_https,
        verify_ssl=verify_ssl,
    )

    # Identify device + read switch capabilities.
    device_info = await client.async_get_device_info()
    caps_raw = await client.async_get_switch_caps()

    switch_caps: list[SwitchCaps] = []
    for item in caps_raw:
        try:
            switch_id = int(item.get("switch"))
        except Exception:
            continue
        switch_caps.append(
            SwitchCaps(
                switch_id=switch_id,
                enabled=bool(item.get("enabled", False)),
                mode=item.get("mode"),
                switch_on_duration=item.get("switchOnDuration"),
                type=item.get("type"),
            )
        )

    # Read logging capabilities once so we can subscribe only to supported events.
    log_caps: set[str] = set()
    try:
        log_caps_list = await client.async_get_log_caps()
        log_caps = {e for e in log_caps_list if isinstance(e, str) and e}
    except TwoNApiError:
        # If caps is unavailable, we fall back to our default filter.
        log_caps = set()

    event_filter = DEFAULT_EVENT_FILTER
    if log_caps:
        # Only subscribe to events supported by this device.
        event_filter = [e for e in DEFAULT_EVENT_FILTER if e in log_caps]

    coordinator = TwoNCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    # Register the device to get a stable Home Assistant device_id for bus events.
    device_registry = dr.async_get(hass)

    identifiers: set[tuple[str, str]] = set()
    if device_info.serial:
        identifiers.add((DOMAIN, device_info.serial))
    elif device_info.mac:
        identifiers.add((DOMAIN, device_info.mac))

    connections: set[tuple[str, str]] = set()
    if device_info.mac:
        connections.add((CONNECTION_NETWORK_MAC, device_info.mac))

    device_entry = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers=identifiers,
        connections=connections,
        manufacturer="2N",
        name=device_info.title,
        model=device_info.model,
        sw_version=device_info.sw_version,
        hw_version=device_info.hw_version,
        serial_number=device_info.serial,
    )

    event_state = TwoNEventState()
    event_manager = TwoNEventManager(
        hass=hass,
        entry_id=entry.entry_id,
        client=client,
        coordinator=coordinator,
        event_state=event_state,
        device_id=device_entry.id,
        event_filter=event_filter,
    )

    entry.runtime_data = TwoNRuntimeData(
        client=client,
        coordinator=coordinator,
        device_info=device_info,
        switch_caps=switch_caps,
        log_caps=log_caps,
        event_filter=event_filter,
        event_state=event_state,
        event_manager=event_manager,
        device_id=device_entry.id,
    )

    await hass.config_entries.async_forward_entry_setups(entry, _HA_PLATFORMS)

    # Start the long-poll event listener after entities are set up.
    if event_filter:
        event_manager.async_start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TwoNConfigEntry) -> bool:
    """Unload a config entry."""

    try:
        entry.runtime_data.event_manager.async_stop()
    except Exception:
        pass

    return await hass.config_entries.async_unload_platforms(entry, _HA_PLATFORMS)
