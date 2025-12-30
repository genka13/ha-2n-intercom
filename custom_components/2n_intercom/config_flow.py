"""Config flow for the 2N Intercom integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TwoNApiError, TwoNClient
from .const import (
    CONF_RTSP_STREAM,
    DEFAULT_RTSP_STREAM,
    AUTH_METHOD_BASIC,
    AUTH_METHOD_DIGEST,
    CONF_AUTH_METHOD,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    CONF_RTSP_PORT,
    DEFAULT_RTSP_PORT,
    CONF_DOOR_RELEASE_SWITCH,
    DEFAULT_DOOR_RELEASE_SWITCH,
    CONF_PULSE_REX,
    DEFAULT_PULSE_REX,
    CONF_PULSE_SILENT_ALARM,
    DEFAULT_PULSE_SILENT_ALARM,
    CONF_PULSE_INVALID_CREDENTIAL,
    DEFAULT_PULSE_INVALID_CREDENTIAL,
)

_LOGGER = logging.getLogger(__name__)

def _user_schema(
    *,
    default_host: str | None = None,
    default_use_https: bool = DEFAULT_USE_HTTPS,
) -> vol.Schema:
    """Build the user step schema.

    We rebuild this schema to allow discovery flows to prefill defaults.
    """

    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=default_host or ""): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(
                CONF_AUTH_METHOD,
                default=AUTH_METHOD_DIGEST,
            ): vol.In([AUTH_METHOD_DIGEST, AUTH_METHOD_BASIC]),
            vol.Optional(CONF_USE_HTTPS, default=default_use_https): bool,
            vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
        }
    )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    session = async_get_clientsession(hass)

    auth_method = data.get(CONF_AUTH_METHOD, AUTH_METHOD_DIGEST)

    client = TwoNClient(
        session=session,
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        auth_method=auth_method,
        use_https=data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
    )

    try:
        info = await client.async_get_device_info()
    except TwoNApiError as err:
        if str(err).lower() in {"unauthorized", "401", "auth"}:
            raise InvalidAuth from err
        raise CannotConnect from err

    return {
        "title": info.title,
        # Prefer MAC so DHCP discovery can update the device reliably.
        "unique_id": info.mac or info.serial or data[CONF_HOST],
    }


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 2N Intercom."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_use_https: bool = DEFAULT_USE_HTTPS

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle discovery via DHCP (MAC prefix / hostname)."""

        self._async_abort_entries_match({CONF_HOST: discovery_info.ip})

        # We can safely use the MAC as unique id without credentials.
        if discovery_info.macaddress:
            await self.async_set_unique_id(format_mac(discovery_info.macaddress))
            self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})

        self._discovered_host = discovery_info.ip
        self._discovered_use_https = DEFAULT_USE_HTTPS
        # Use hostname (when available) for the UI title. It is easier to recognize than a MAC.
        host = discovery_info.hostname or discovery_info.ip
        name = discovery_info.ip
        if host and host != discovery_info.ip:
            name = f"{host} ({discovery_info.ip})"
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.get("unique_id"))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(
                default_host=self._discovered_host,
                default_use_https=self._discovered_use_https,
            ),
            errors=errors,
        )



    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return TwoNOptionsFlowHandler(config_entry)

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class TwoNOptionsFlowHandler(OptionsFlow):
    """Handle options for 2N Intercom."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry


    async def _async_get_door_release_switch_choices(self) -> list[int]:
        """Return allowed switch IDs for the Door release button.

        Prefer *enabled* switches from /api/switch/caps. If no switch is enabled,
        fall back to the list of available switch IDs. As a final fallback,
        allow 1..64.
        """
        # Try runtime data (already fetched during setup).
        rt = getattr(self._entry, "runtime_data", None)
        switch_caps = getattr(rt, "switch_caps", None) if rt else None
        if switch_caps:
            enabled = sorted({c.switch_id for c in switch_caps if getattr(c, 'enabled', False)})
            if enabled:
                return enabled

            available = sorted({c.switch_id for c in switch_caps})
            if available:
                return available

        # Fallback: query the device directly (best-effort).
        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            from .api import TwoNClient
            from .const import (
                AUTH_METHOD_DIGEST,
                CONF_AUTH_METHOD,
                CONF_USE_HTTPS,
                CONF_VERIFY_SSL,
                DEFAULT_USE_HTTPS,
                DEFAULT_VERIFY_SSL,
            )

            session = async_get_clientsession(self.hass)
            host: str = self._entry.data[CONF_HOST]
            username: str = self._entry.data[CONF_USERNAME]
            password: str = self._entry.data[CONF_PASSWORD]
            use_https: bool = self._entry.data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS)
            verify_ssl: bool = self._entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            auth_method: str = self._entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_DIGEST)

            client = TwoNClient(
                session=session,
                host=host,
                username=username,
                password=password,
                auth_method=auth_method,
                use_https=use_https,
                verify_ssl=verify_ssl,
            )
            caps_raw = await client.async_get_switch_caps()
            enabled = sorted({int(item.get('switch')) for item in caps_raw if isinstance(item, dict) and item.get('enabled') is True and 'switch' in item})
            if enabled:
                return enabled
            available = sorted({int(item.get('switch')) for item in caps_raw if isinstance(item, dict) and 'switch' in item})
            if available:
                return available
        except Exception:
            # Any error -> fall back to wide range
            pass

        return list(range(1, 65))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        door_release_choices = await self._async_get_door_release_switch_choices()
        default_door_release = int(opts.get(CONF_DOOR_RELEASE_SWITCH, DEFAULT_DOOR_RELEASE_SWITCH))
        if default_door_release not in door_release_choices and door_release_choices:
            default_door_release = door_release_choices[0]
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_RTSP_STREAM,
                    default=opts.get(CONF_RTSP_STREAM, DEFAULT_RTSP_STREAM),
                ): vol.In(["h264_stream", "h265_stream", "mjpeg_stream"]),
                vol.Optional(
                    CONF_RTSP_PORT,
                    default=int(opts.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_DOOR_RELEASE_SWITCH,
                    default=default_door_release,
                ): vol.In(door_release_choices),
                vol.Optional(
                    CONF_PULSE_REX,
                    default=int(opts.get(CONF_PULSE_REX, DEFAULT_PULSE_REX)),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                vol.Optional(
                    CONF_PULSE_SILENT_ALARM,
                    default=int(opts.get(CONF_PULSE_SILENT_ALARM, DEFAULT_PULSE_SILENT_ALARM)),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
                vol.Optional(
                    CONF_PULSE_INVALID_CREDENTIAL,
                    default=int(opts.get(CONF_PULSE_INVALID_CREDENTIAL, DEFAULT_PULSE_INVALID_CREDENTIAL)),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
