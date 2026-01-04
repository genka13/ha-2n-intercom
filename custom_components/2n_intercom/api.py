"""API shim.

Protocol and device API implementation lives in the external PyPI library:
`py2n-intercom` (import package: `py2n_intercom`).
"""

from py2n_intercom.client import (
    Py2NApiError,
    Py2NClient,
    Py2NDeviceInfo,
    Py2NLogEvent,
)

__all__ = [
    "Py2NApiError",
    "Py2NClient",
    "Py2NDeviceInfo",
    "Py2NLogEvent",
]
