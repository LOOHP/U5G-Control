"""Normalize radio-status values across U5G firmware variants."""

from __future__ import annotations

from typing import Any


def _optional_bool(value: Any) -> bool | None:
    """Normalize native and string boolean values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def current_mode(status: dict[str, Any]) -> str:
    """Return a consistent active mode label for one radio-status payload."""
    raw_mode = str(
        status.get("rat-mode-active") or status.get("mode") or ""
    ).strip()
    normalized_mode = raw_mode.upper()
    sa_active = _optional_bool(status.get("5g-sa-mode"))

    if "NSA" in normalized_mode:
        return "5G NSA"
    if "SA" in normalized_mode and "NSA" not in normalized_mode:
        return "5G SA"

    has_nr = (
        "5G" in normalized_mode
        or "NR" in normalized_mode
        or bool(status.get("ca-nr"))
    )
    has_lte = "LTE" in normalized_mode or bool(status.get("ca-lte"))

    if has_nr and sa_active is True:
        return "5G SA"
    if has_nr and (has_lte or sa_active is False):
        return "5G NSA"
    if has_nr:
        return "5G"
    if has_lte:
        return "LTE"
    return raw_mode or "Unknown"


def sa_is_active(status: dict[str, Any]) -> bool:
    """Return whether 5G standalone is currently active."""
    return current_mode(status) == "5G SA"


def nsa_is_active(status: dict[str, Any]) -> bool:
    """Return whether 5G non-standalone is currently active."""
    return current_mode(status) == "5G NSA"
