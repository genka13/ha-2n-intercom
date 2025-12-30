"""Async HTTP client for 2N IP intercoms (HTTP API).

Targets the /api/* endpoints as used by 2N IP Style / Verso 2 / One.

Auth:
- Basic: supported via aiohttp.BasicAuth
- Digest: implemented client-side (RFC 7616 subset; supports MD5/SHA-* and -sess variants)

Most 2N endpoints used here are GET-based.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    API_CAMERA_CAPS,
    API_CAMERA_SNAPSHOT,
    API_LOG_CAPS,
    API_LOG_PULL,
    API_LOG_SUBSCRIBE,
    API_LOG_UNSUBSCRIBE,
    API_SWITCH_CAPS,
    API_SWITCH_CTRL,
    API_SWITCH_STATUS,
    API_SYSTEM_INFO,
    AUTH_METHOD_BASIC,
    AUTH_METHOD_DIGEST,
)


def _normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    # Accept formats like 7c-1e-b3-eb-40-a9 or 7C:1E:B3:...
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(cleaned) != 12:
        return None
    pairs = [cleaned[i : i + 2] for i in range(0, 12, 2)]
    return ":".join(p.upper() for p in pairs)


class TwoNApiError(Exception):
    """Raised on communication/auth errors with the 2N device."""


@dataclass(slots=True)
class TwoNDeviceInfo:
    """Metadata extracted from /api/system/info."""

    title: str
    model: str | None = None
    serial: str | None = None
    mac: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    boot_uuid: str | None = None


_digest_kv_split = re.compile(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)")


def _parse_www_authenticate(header_value: str) -> dict[str, str]:
    """Parse a Digest WWW-Authenticate header into a dict.

    This is a permissive parser good enough for typical embedded devices.
    """

    if not header_value:
        return {}

    # Some servers send multiple challenges; pick the Digest one.
    hv = header_value.strip()
    if "Digest" not in hv:
        return {}

    # Keep only the part starting at 'Digest'
    idx = hv.find("Digest")
    hv = hv[idx + len("Digest") :].strip()

    out: dict[str, str] = {}
    for part in _digest_kv_split.split(hv):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if v.startswith('"') and v.endswith('"') and len(v) >= 2:
            v = v[1:-1]
        out[k] = v
    return out


def _hash_for_algorithm(algorithm: str):
    alg = (algorithm or "MD5").upper()
    if alg.startswith("MD5"):
        return hashlib.md5
    if alg.startswith("SHA-256"):
        return hashlib.sha256
    if alg.startswith("SHA-512"):
        return hashlib.sha512
    if alg.startswith("SHA"):
        return hashlib.sha1
    return hashlib.md5


def _h(hash_ctor, data: str) -> str:
    return hash_ctor(data.encode("utf-8")).hexdigest()


class _DigestState:
    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._nonce_counts: dict[str, int] = {}

    def build_authorization(self, *, method: str, url: URL, www_authenticate: str) -> str:
        params = _parse_www_authenticate(www_authenticate)
        if not params:
            raise TwoNApiError("digest_challenge_missing")

        realm = params.get("realm", "")
        nonce = params.get("nonce", "")
        qop_raw = params.get("qop", "")
        algorithm = params.get("algorithm", "MD5")
        opaque = params.get("opaque")

        if not realm or not nonce:
            raise TwoNApiError("digest_challenge_incomplete")

        # Choose qop
        qop: str | None = None
        if qop_raw:
            qops = [q.strip() for q in qop_raw.split(",") if q.strip()]
            if "auth" in qops:
                qop = "auth"
            elif qops:
                qop = qops[0]

        hash_ctor = _hash_for_algorithm(algorithm)

        uri = url.raw_path_qs
        cnonce = os.urandom(8).hex()

        # nonce count per nonce
        nc_int = self._nonce_counts.get(nonce, 0) + 1
        self._nonce_counts[nonce] = nc_int
        nc = f"{nc_int:08x}"

        # HA1 / HA2 per RFC 7616
        alg_up = (algorithm or "MD5").upper()
        ha1 = _h(hash_ctor, f"{self._username}:{realm}:{self._password}")
        if alg_up.endswith("-SESS"):
            ha1 = _h(hash_ctor, f"{ha1}:{nonce}:{cnonce}")

        ha2 = _h(hash_ctor, f"{method}:{uri}")

        if qop:
            response = _h(hash_ctor, f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        else:
            response = _h(hash_ctor, f"{ha1}:{nonce}:{ha2}")

        # Build header string (quote most values)
        header_parts: list[str] = []
        header_parts.append(f'Digest username="{self._username}"')
        header_parts.append(f'realm="{realm}"')
        header_parts.append(f'nonce="{nonce}"')
        header_parts.append(f'uri="{uri}"')
        header_parts.append(f'response="{response}"')

        if algorithm:
            header_parts.append(f"algorithm={algorithm}")
        if opaque:
            header_parts.append(f'opaque="{opaque}"')
        if qop:
            header_parts.append(f"qop={qop}")
            header_parts.append(f"nc={nc}")
            header_parts.append(f'cnonce="{cnonce}"')

        return ", ".join(header_parts)


class TwoNClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        auth_method: str = AUTH_METHOD_DIGEST,
        use_https: bool = True,
        verify_ssl: bool = True,
    ) -> None:
        self._session = session
        self._ssl = verify_ssl
        self._auth_method = auth_method
        self._basic_auth: aiohttp.BasicAuth | None = None
        self._digest: _DigestState | None = None

        if auth_method == AUTH_METHOD_BASIC:
            self._basic_auth = aiohttp.BasicAuth(username, password)
        else:
            self._digest = _DigestState(username, password)

        if host.startswith("http://") or host.startswith("https://"):
            self._base = URL(host)
        else:
            scheme = "https" if use_https else "http"
            self._base = URL.build(scheme=scheme, host=host)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        want: str = "json",
        timeout_total: int = 10,
    ) -> Any:
        url = self._base.join(URL(path))
        timeout = aiohttp.ClientTimeout(total=timeout_total)

        async def _do(headers: dict[str, str] | None = None) -> aiohttp.ClientResponse:
            return await self._session.request(
                method,
                url,
                params=params,
                auth=self._basic_auth,
                headers=headers,
                ssl=self._ssl,
                timeout=timeout,
            )

        try:
            resp = await _do()
            try:
                if resp.status == 401 and self._auth_method == AUTH_METHOD_DIGEST and self._digest is not None:
                    www = resp.headers.get("WWW-Authenticate", "")
                    await resp.release()

                    authz = self._digest.build_authorization(method=method, url=url, www_authenticate=www)
                    resp = await _do(headers={"Authorization": authz})

                if resp.status == 401:
                    raise TwoNApiError("unauthorized")
                if resp.status >= 400:
                    text = await resp.text()
                    raise TwoNApiError(f"HTTP {resp.status}: {text}")

                if want == "response":
                    return resp

                if want == "bytes":
                    return await resp.read()

                data = await resp.json()
                if not isinstance(data, dict) or not data.get("success", False):
                    raise TwoNApiError(f"unexpected_response: {data}")
                return data
            finally:
                if want != "response":
                    await resp.release()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise TwoNApiError(str(err)) from err

    async def async_get_device_info(self) -> TwoNDeviceInfo:
        data = await self._request("GET", API_SYSTEM_INFO)
        result = data.get("result") or {}

        title = (result.get("deviceName") or result.get("variant") or "2N").strip()
        return TwoNDeviceInfo(
            title=title,
            model=result.get("variant"),
            serial=result.get("serialNumber"),
            mac=_normalize_mac(result.get("macAddr")),
            sw_version=result.get("swVersion"),
            hw_version=result.get("hwVersion"),
            boot_uuid=result.get("bootUuid"),
        )

    async def async_open_snapshot_stream(
        self,
        *,
        width: int,
        height: int,
        source: str = "internal",
        fps: int = 10,
    ) -> aiohttp.ClientResponse:
        """Open a multipart MJPEG stream from the intercom snapshot endpoint.

        The 2N API returns image/jpeg when fps is omitted, and multipart/x-mixed-replace when fps >= 1.
        """

        params: dict[str, Any] = {
            "width": width,
            "height": height,
            "source": source,
            "fps": str(max(1, int(fps))),
        }
        return await self._request("GET", API_CAMERA_SNAPSHOT, params=params, want="response")

    async def async_get_switch_caps(self) -> list[dict[str, Any]]:
        data = await self._request("GET", API_SWITCH_CAPS)
        result = data.get("result") or {}
        switches = result.get("switches") or []
        if not isinstance(switches, list):
            return []
        return [s for s in switches if isinstance(s, dict)]

    async def async_get_switch_status(self) -> list[dict[str, Any]]:
        data = await self._request("GET", API_SWITCH_STATUS)
        result = data.get("result") or {}
        switches = result.get("switches") or []
        if not isinstance(switches, list):
            return []
        return [s for s in switches if isinstance(s, dict)]

    async def async_trigger_switch(self, switch_id: int) -> None:
        await self._request(
            "GET",
            API_SWITCH_CTRL,
            params={"switch": switch_id, "action": "trigger"},
            want="json",
        )

    async def async_get_camera_caps(self) -> list[tuple[int, int]]:
        """Return supported snapshot resolutions as list of (width, height)."""

        # /api/camera/caps returns JSON in the same {success,result} envelope.
        # Some devices / user roles may not have access to this endpoint; fall back gracefully.
        try:
            data = await self._request("GET", API_CAMERA_CAPS)
        except TwoNApiError:
            return [(640, 480), (1280, 960)]

        # Expected shape:
        # {"success": true, "result": {"resolutions":[{"width":640,"height":480}, ...]}}
        result = data.get("result") or {}
        resolutions = result.get("resolutions") or result.get("resolution") or []
        out: list[tuple[int, int]] = []
        for item in resolutions:
            try:
                w = int(item.get("width"))
                h = int(item.get("height"))
            except Exception:
                continue
            if w > 0 and h > 0:
                out.append((w, h))
        return out or [(640, 480), (1280, 960)]

    async def async_get_snapshot(self, *, width: int = 640, height: int = 480, source: str = "internal") -> bytes:
        """Fetch a single JPEG snapshot."""

        return await self._request(
            "GET",
            API_CAMERA_SNAPSHOT,
            params={"width": width, "height": height, "source": source},
            want="bytes",
        )

    async def async_get_log_caps(self) -> list[str]:
        """Return the list of supported log event types ("/api/log/caps")."""

        data = await self._request("GET", API_LOG_CAPS)
        result = data.get("result") or {}
        events = result.get("events") or []
        if not isinstance(events, list):
            return []
        out: list[str] = []
        for e in events:
            if isinstance(e, str) and e:
                out.append(e)
        return out

    async def async_log_subscribe(
        self,
        *,
        event_filter: list[str] | None = None,
        include: str = "new",
        duration: int = 3600,
    ) -> int:
        """Create a log subscription channel and return its id."""

        params: dict[str, Any] = {"include": include, "duration": duration}
        if event_filter:
            params["filter"] = ",".join(event_filter)

        data = await self._request("GET", API_LOG_SUBSCRIBE, params=params)
        result = data.get("result") or {}
        try:
            return int(result.get("id"))
        except Exception as err:
            raise TwoNApiError(f"unexpected_response: {data}") from err

    async def async_log_pull(self, channel_id: int, *, timeout: int = 0) -> list[dict[str, Any]]:
        """Pull events from the log subscription queue (long-poll)."""

        params = {"id": channel_id, "timeout": timeout}
        data = await self._request(
            "GET",
            API_LOG_PULL,
            params=params,
            timeout_total=max(10, int(timeout) + 10),
        )
        result = data.get("result") or {}
        events = result.get("events") or []
        if not isinstance(events, list):
            return []
        return [e for e in events if isinstance(e, dict)]

    async def async_log_unsubscribe(self, channel_id: int) -> None:
        """Close a log subscription channel."""

        await self._request("GET", API_LOG_UNSUBSCRIBE, params={"id": channel_id})
