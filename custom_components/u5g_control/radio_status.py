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
    return raw_mode or "Not connected"


def sa_is_active(status: dict[str, Any]) -> bool:
    """Return whether 5G standalone is currently active."""
    return current_mode(status) == "5G SA"


def nsa_is_active(status: dict[str, Any]) -> bool:
    """Return whether 5G non-standalone is currently active."""
    return current_mode(status) == "5G NSA"


def lte_measurement(status: dict[str, Any], key: str) -> Any:
    """Return a generic radio measurement only when LTE is active.

    U5G firmware mirrors NR measurements into the generic fields during SA,
    so those fields cannot be treated as LTE values in standalone mode.
    """
    mode = current_mode(status)
    if mode == "5G SA" or mode == "Not connected":
        return None
    if mode in {"LTE", "5G NSA"} or bool(status.get("ca-lte")):
        return status.get(key)
    return None


def rounded_measurement(value: Any, digits: int = 1) -> Any:
    """Round a numeric radio measurement without changing missing values."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value, digits)
    return value


def signal_quality_percentage(status: dict[str, Any]) -> int | None:
    """Calculate composite signal quality using the active radio measurements.

    This follows NetworkOptimizer's calculation: RSRP contributes 50%, SINR
    30%, and RSRQ 20%. NR measurements take priority whenever they are
    available; otherwise the active LTE measurements are used. Missing metrics
    are omitted and the remaining weights are normalized.
    """
    mode = current_mode(status)
    nr_rsrp = status.get("rsrp-nr")
    use_nr = _is_number(nr_rsrp)

    if use_nr:
        rsrp = nr_rsrp
        rsrq = status.get("rsrq-nr")
        sinr = status.get("snr-nr")
    elif mode == "5G SA":
        # Some firmware reports SA measurements only in the generic fields.
        rsrp = status.get("rsrp")
        rsrq = status.get("rsrq")
        sinr = status.get("snr")
        use_nr = _is_number(rsrp)
    else:
        rsrp = lte_measurement(status, "rsrp")
        rsrq = lte_measurement(status, "rsrq")
        sinr = lte_measurement(status, "snr")

    weighted_score = 0.0
    total_weight = 0.0

    if _is_number(rsrp):
        floor = -110 if use_nr else -120
        score = _clamp((float(rsrp) - floor) * (100.0 / 30.0))
        weighted_score += score * 0.5
        total_weight += 0.5

    if _is_number(sinr):
        score = _clamp(float(sinr) * (100.0 / 30.0))
        weighted_score += score * 0.3
        total_weight += 0.3

    if _is_number(rsrq):
        score = _clamp((float(rsrq) + 20) * (100.0 / 17.0))
        weighted_score += score * 0.2
        total_weight += 0.2

    if total_weight == 0:
        return None
    return int(weighted_score / total_weight)


def _is_number(value: Any) -> bool:
    """Return whether a value is a usable numeric radio measurement."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clamp(value: float) -> float:
    """Clamp one calculated score to the percentage range."""
    return max(0.0, min(100.0, value))


def roaming_is_active(status: dict[str, Any]) -> bool | None:
    """Return roaming status, or None when the radio is disconnected."""
    if current_mode(status) == "Not connected" or "roaming" not in status:
        return None
    value = _optional_bool(status.get("roaming"))
    if value is None and isinstance(status.get("roaming"), int):
        value = bool(status["roaming"])
    return value
