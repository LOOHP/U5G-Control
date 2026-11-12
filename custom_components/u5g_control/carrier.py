"""Firmware-independent component-carrier value normalization."""

from __future__ import annotations

import re
from typing import Any

_DOWNLINK_BANDWIDTH_KEYS = (
    "dlbwmhz",
    "dlbandwidthmhz",
    "dlbandwidth",
    "dlbw",
    "dlchannelbandwidth",
    "downlinkbandwidth",
    "bandwidthdl",
    "bandwidthmhz",
    "bandwidthkhz",
    "bandwidthhz",
    "bandwidth",
    "channelbandwidth",
    "receivebandwidth",
    "rxbandwidth",
    "rxbw",
    "width",
    "bw",
)

_UPLINK_BANDWIDTH_KEYS = (
    "ulbwmhz",
    "ulbandwidthmhz",
    "ulbandwidth",
    "ulbw",
    "ulchannelbandwidth",
    "uplinkbandwidth",
    "bandwidthul",
    "transmitbandwidth",
    "txbandwidth",
    "txbw",
)


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())


def _as_mhz(value: Any, normalized_key: str) -> int | float | None:
    """Convert a numeric bandwidth value and its reported unit to MHz."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        unit_source = normalized_key
    else:
        text = str(value).strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
        unit_source = _normalized_key(text)

    if "ghz" in unit_source:
        number *= 1000
    elif "khz" in unit_source:
        number /= 1000
    elif "mhz" not in unit_source and "hz" in unit_source:
        number /= 1_000_000

    return int(number) if number.is_integer() else number


def _carrier_width_mhz(
    carrier: dict[str, Any] | None, keys: tuple[str, ...]
) -> int | float | None:
    """Read one directional carrier width across firmware variants."""
    if carrier is None:
        return None

    normalized_values = {
        _normalized_key(key): value for key, value in carrier.items()
    }
    for normalized_key in keys:
        if normalized_key in normalized_values:
            result = _as_mhz(normalized_values[normalized_key], normalized_key)
            if result is not None:
                return result

    for value in carrier.values():
        if isinstance(value, dict):
            result = _carrier_width_mhz(value, keys)
            if result is not None:
                return result
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result = _carrier_width_mhz(item, keys)
                    if result is not None:
                        return result
    return None


def carrier_downlink_width_mhz(
    carrier: dict[str, Any] | None,
) -> int | float | None:
    """Read a carrier's download width in MHz."""
    return _carrier_width_mhz(carrier, _DOWNLINK_BANDWIDTH_KEYS)


def carrier_uplink_width_mhz(
    carrier: dict[str, Any] | None,
) -> int | float | None:
    """Read a carrier's upload width in MHz when explicitly reported."""
    return _carrier_width_mhz(carrier, _UPLINK_BANDWIDTH_KEYS)


def carrier_width_mhz(carrier: dict[str, Any] | None) -> int | float | None:
    """Return the download width for backward-compatible callers."""
    return carrier_downlink_width_mhz(carrier)
