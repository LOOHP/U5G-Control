"""Parse optional Sierra Wireless radio diagnostics."""

from __future__ import annotations

import re
from html import unescape
from typing import Any


_NR_BLOCK = re.compile(r"(?=NR5G band:\s*n?\d+)", re.IGNORECASE)
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_LTE_BANDWIDTHS = {0: 1.4, 1: 3, 2: 5, 3: 10, 4: 15, 5: 20}


def _number(value: str) -> int | float:
    """Return a compact numeric value."""
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _field(block: str, pattern: str) -> str | None:
    match = re.search(pattern, block, re.IGNORECASE)
    if match is None:
        return None
    value = match.group(1).strip()
    return None if value in {"---", "Unknown"} else value


def parse_sierra_nrinfo(output: str) -> list[dict[str, Any]]:
    """Parse per-carrier data from ``AT!NRINFO?`` output.

    Sierra reports RSRP, RSRQ and SINR only once after all NR carrier blocks,
    so those connection-level values are deliberately not assigned to an
    individual component carrier.
    """
    start = output.find("NR5G band:")
    if start < 0:
        return []

    carriers: list[dict[str, Any]] = []
    for block in _NR_BLOCK.split(output[start:]):
        if not block.lstrip().lower().startswith("nr5g band:"):
            continue
        band = _field(block, r"NR5G band:\s*n?(\d+)")
        if band is None:
            continue
        carrier: dict[str, Any] = {"band": int(band)}

        fields = {
            "carrier-id": r"NR5G Carrier ID:\s*(\d+)",
            "dl-bw-mhz": r"NR5G dl bw:\s*([\d.]+)\s*MHz",
            "ul-bw-mhz": r"NR5G ul bw:\s*([\d.]+)\s*MHz",
            "tx-power-dbm": r"NR5G Tx Power:\s*(-?[\d.]+)",
            "ul-arfcn": r"NR5G Tx chan:\s*(\d+)",
            "dl-arfcn": r"NR5G Rx chan:\s*(\d+)",
            "dl-mimo-layers": r"NR5G dl MIMO:\s*(\d+)",
            "ul-mimo-layers": r"NR5G ul MIMO:\s*(\d+)",
        }
        for key, pattern in fields.items():
            value = _field(block, pattern)
            if value is not None and _NUMBER.match(value):
                carrier[key] = _number(value)

        rssi_paths = {
            int(path): float(value)
            for path, value in re.findall(
                r"NR5G\((?:sub6|mmw)\) Rx(\d+) RSSI \(dBm\):\s*(-?[\d.]+)",
                block,
                re.IGNORECASE,
            )
        }
        for path, value in sorted(rssi_paths.items()):
            carrier[f"rssi-rx{path}-dbm"] = value
        if rssi_paths:
            values = list(rssi_paths.values())
            carrier["rssi-dbm"] = max(values)
            carrier["rssi-average-dbm"] = round(sum(values) / len(values), 1)

        carrier_id = carrier.get("carrier-id")
        if carrier_id is not None:
            carrier["primary"] = carrier_id == 0
        carriers.append(carrier)
    return carriers


def merge_sierra_nrinfo(
    radio_status: dict[str, Any], output: str
) -> dict[str, Any]:
    """Merge Sierra NR diagnostics into uiwwand component carriers."""
    diagnostics = parse_sierra_nrinfo(output)
    if not diagnostics:
        return radio_status

    existing_value = radio_status.get("ca-nr")
    existing = (
        [dict(item) for item in existing_value if isinstance(item, dict)]
        if isinstance(existing_value, list)
        else []
    )
    used: set[int] = set()
    merged: list[dict[str, Any]] = []

    for diagnostic in diagnostics:
        match_index: int | None = None
        diagnostic_band = diagnostic.get("band")
        diagnostic_channel = diagnostic.get("dl-arfcn")
        for index, carrier in enumerate(existing):
            if index in used or carrier.get("band") != diagnostic_band:
                continue
            existing_channel = carrier.get("dl-arfcn", carrier.get("arfcn"))
            if (
                existing_channel is not None
                and diagnostic_channel is not None
                and existing_channel != diagnostic_channel
            ):
                continue
            match_index = index
            break

        if match_index is None:
            merged.append(diagnostic)
        else:
            used.add(match_index)
            merged.append({**existing[match_index], **diagnostic})

    merged.extend(carrier for index, carrier in enumerate(existing) if index not in used)
    radio_status["ca-nr"] = merged
    return radio_status


def _lte_bandwidth(value: str) -> int | float | None:
    """Decode Sierra's LTE bandwidth enumeration."""
    try:
        return _LTE_BANDWIDTHS.get(int(value))
    except ValueError:
        return None


def parse_sierra_lteinfo(output: str) -> list[dict[str, Any]]:
    """Parse serving and CA component carriers from ``AT!LTEINFO?``."""
    carriers: list[dict[str, Any]] = []
    section: str | None = None
    for raw_line in output.splitlines():
        line = unescape(raw_line).strip()
        if line.startswith("Serving:"):
            section = "serving"
            continue
        if line.startswith("CA SCell"):
            section = "secondary"
            continue
        if line.startswith(("IntraFreq:", "InterFreq:", "WCDMA:", "OK")):
            section = None
            continue
        if not line or section is None:
            continue

        values = line.split()
        if section == "serving" and len(values) >= 14:
            try:
                carrier: dict[str, Any] = {
                    "primary": True,
                    "dl-earfcn": int(values[0]),
                    "band": int(values[5]),
                    "pci": int(values[9]),
                    "sinr-db": float(values[8]),
                    "rsrq-db": float(values[10]),
                    "rsrp-dbm": float(values[11]),
                    "rssi-dbm": float(values[12]),
                }
            except ValueError:
                continue
            if (width := _lte_bandwidth(values[6])) is not None:
                carrier["dl-bw-mhz"] = width
            if (width := _lte_bandwidth(values[7])) is not None:
                carrier["ul-bw-mhz"] = width
            carriers.append(carrier)
            section = None
        elif section == "secondary" and len(values) >= 12:
            try:
                carrier = {
                    "primary": False,
                    "dl-earfcn": int(values[0]),
                    "secondary-cell-id": int(values[1]),
                    "band": int(values[2]),
                    "state": int(values[3]),
                    "dl-mimo-layers": int(values[6]),
                    "ul-mimo-layers": int(values[7]),
                    "pci": int(values[8]),
                    "rsrp-dbm": float(values[9]),
                    "rssi-dbm": float(values[10]),
                    "sinr-db": float(values[11]),
                }
            except ValueError:
                continue
            if (width := _lte_bandwidth(values[4])) is not None:
                carrier["dl-bw-mhz"] = width
            if (width := _lte_bandwidth(values[5])) is not None:
                carrier["ul-bw-mhz"] = width
            carriers.append(carrier)
    return carriers


def merge_sierra_lteinfo(
    radio_status: dict[str, Any], output: str
) -> dict[str, Any]:
    """Merge Sierra LTE diagnostics into uiwwand component carriers."""
    diagnostics = parse_sierra_lteinfo(output)
    if not diagnostics:
        return radio_status

    existing_value = radio_status.get("ca-lte")
    existing = (
        [dict(item) for item in existing_value if isinstance(item, dict)]
        if isinstance(existing_value, list)
        else []
    )
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        match_index: int | None = None
        for index, carrier in enumerate(existing):
            if index in used or carrier.get("band") != diagnostic.get("band"):
                continue
            existing_channel = carrier.get("dl-earfcn", carrier.get("earfcn"))
            if (
                existing_channel is not None
                and existing_channel != diagnostic.get("dl-earfcn")
            ):
                continue
            match_index = index
            break
        if match_index is None:
            merged.append(diagnostic)
        else:
            used.add(match_index)
            merged.append({**existing[match_index], **diagnostic})
    merged.extend(carrier for index, carrier in enumerate(existing) if index not in used)
    radio_status["ca-lte"] = merged
    return radio_status
