"""Data update coordinator for 2N Intercom.

All HTTP communication is performed by the external py2n-intercom library.
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Py2NApiError, Py2NClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Py2NCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator that periodically polls switch status."""

    def __init__(self, hass: HomeAssistant, client: Py2NClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            status = await self.client.async_get_switch_status()
            # Map by switch number for fast access
            by_id: dict[int, dict] = {}
            for item in status:
                try:
                    sid = int(item.get("switch"))
                except Exception:
                    continue
                by_id[sid] = item
            return {"switches": by_id}
        except Py2NApiError as err:
            raise UpdateFailed(str(err)) from err