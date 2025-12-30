"""Shared models for 2N Intercom."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SwitchCaps:
    """Capabilities for a given 2N "switch" (relay)."""

    switch_id: int
    enabled: bool
    mode: str | None = None
    switch_on_duration: int | None = None
    type: str | None = None
