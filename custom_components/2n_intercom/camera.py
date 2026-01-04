"""Camera platform for 2N Intercom (snapshot + RTSP stream source)."""

from __future__ import annotations

from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from aiohttp import web

from homeassistant.helpers.aiohttp_client import async_aiohttp_proxy_stream

from . import Py2NConfigEntry
from .const import CONF_RTSP_STREAM, DEFAULT_RTSP_STREAM, CONF_RTSP_PORT, DEFAULT_RTSP_PORT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Py2NConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([Py2NSnapshotCamera(entry)])


class Py2NSnapshotCamera(Camera):
    """A snapshot camera entity backed by /api/camera/snapshot."""

    _attr_has_entity_name = True
    # Home Assistant expects supported_features to be a CameraEntityFeature (IntFlag),
    # not a plain int. Different HA versions expose different feature flags.
    _attr_supported_features = CameraEntityFeature(0)
    _attr_content_type = "image/jpeg"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__()
        self._entry = entry
        self._client = entry.runtime_data.client
        self._supported_resolutions: list[tuple[int, int]] | None = None
        self._attr_unique_id = f"{entry.entry_id}_snapshot"
        self._attr_name = "Camera"

        # Build supported features dynamically for compatibility across HA versions.
        features = CameraEntityFeature(0)
        for feature_name in ("SNAPSHOT", "MJPEG", "STREAM"):
            if hasattr(CameraEntityFeature, feature_name):
                features |= getattr(CameraEntityFeature, feature_name)
        self._attr_supported_features = features

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

    async def _select_resolution(self, width: int | None, height: int | None) -> tuple[int, int]:
        """Choose the smallest supported resolution that meets requested min size."""
        if self._supported_resolutions is None:
            try:
                self._supported_resolutions = await self._client.async_get_camera_caps()
            except Exception:
                # Some devices/users may not have permissions for /api/camera/caps.
                # Fall back to a conservative default.
                self._supported_resolutions = [(640, 480)]

            # Sort by area ascending to pick the smallest that still fits.
            self._supported_resolutions.sort(key=lambda r: r[0] * r[1])

        req_w = width or 640
        req_h = height or 480
        for w, h in self._supported_resolutions:
            if w >= req_w and h >= req_h:
                return w, h
        # If none match, return the largest available.
        return self._supported_resolutions[-1]

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        w, h = await self._select_resolution(width, height)
        return await self._client.async_get_snapshot(width=w, height=h)

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """Proxy a multipart MJPEG stream from the intercom.

        Home Assistant may use /api/camera_proxy_stream for the "more info" dialog.
        The 2N snapshot endpoint supports multipart streaming when fps >= 1.
        """
        width = request.query.get("width")
        height = request.query.get("height")
        req_w = int(width) if width and width.isdigit() else 640
        req_h = int(height) if height and height.isdigit() else 480

        w, h = await self._select_resolution(req_w, req_h)

        fps = int(self._entry.options.get("mjpeg_fps", 10))
        resp = await self._client.async_open_snapshot_stream(width=w, height=h, fps=fps)

        content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace")
        try:
            return await async_aiohttp_proxy_stream(
                self.hass, request, resp.content, content_type
            )
        finally:
            resp.close()


    async def stream_source(self) -> str | None:
        """Return the RTSP stream source.

        2N devices expose fixed RTSP endpoints:
        - /h264_stream
        - /h265_stream
        - /mjpeg_stream
        """
        from yarl import URL

        host = self._entry.data.get(CONF_HOST)
        username = self._entry.data.get(CONF_USERNAME)
        password = self._entry.data.get(CONF_PASSWORD)
        if not host:
            return None

        stream_name = str(self._entry.options.get(CONF_RTSP_STREAM, DEFAULT_RTSP_STREAM)).strip("/")
        url = URL.build(
            scheme="rtsp",
            host=host,
            port=int(self._entry.options.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)),
            path=f"/{stream_name}",
        )
        if username and password:
            url = url.with_user(str(username)).with_password(str(password))
        return str(url)
