"""Privacy helpers without Home Assistant dependencies."""

from __future__ import annotations

from typing import Any

_REDACT_KEYS = {
    "arfcn",
    "cellid",
    "channel",
    "dlarfcn",
    "dlearfcn",
    "earfcn",
    "eci",
    "globalcellid",
    "iccid",
    "nci",
    "ncgi",
    "pci",
    "physicalcellid",
    "rxchannel",
    "tac",
    "trackingareacode",
    "txchannel",
    "ularfcn",
    "ulearfcn",
}


def _normalized_key(value: object) -> str:
    """Normalize case and separators in a diagnostic field name."""
    return "".join(character for character in str(value).casefold() if character.isalnum())


def redact_diagnostics(value: Any) -> Any:
    """Recursively redact location-bearing cellular identifiers."""
    if isinstance(value, dict):
        return {
            key: (
                "REDACTED"
                if _normalized_key(key) in _REDACT_KEYS
                else redact_diagnostics(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_diagnostics(item) for item in value]
    return value
