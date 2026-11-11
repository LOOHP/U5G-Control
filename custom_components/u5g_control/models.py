"""Data models used by U5G Control.

This module deliberately has no Home Assistant dependencies so its policy and
persistence behavior can be unit tested in isolation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any


def parse_band_list(value: str | list[int] | tuple[int, ...] | set[int] | None) -> set[int]:
    """Parse a uiwwand comma-separated band list."""
    if value is None:
        return set()
    if isinstance(value, str):
        return {int(item.strip()) for item in value.split(",") if item.strip().isdigit()}
    return {int(item) for item in value}


def format_band_list(value: set[int] | list[int] | tuple[int, ...]) -> str:
    """Format a band collection for uiwwand."""
    return ",".join(str(item) for item in sorted({int(item) for item in value}))


def sim_identifier(modem_id: str, iccid: str) -> str:
    """Return a stable, privacy-safe identifier for a SIM in one modem."""
    return sha256(f"{modem_id}:{iccid}".encode()).hexdigest()[:20]


def sim_display_name(spn: str | None, mcc: int | None, mnc: int | None, iccid: str) -> str:
    """Build a friendly SIM name without exposing the full ICCID."""
    provider = (spn or "").strip()
    if not provider and mcc is not None and mnc is not None:
        provider = f"{mcc}-{mnc:02d}"
    if not provider:
        provider = "SIM"
    suffix = iccid[-4:] if len(iccid) >= 4 else "unknown"
    return f"{provider} [{suffix}]"


@dataclass(slots=True)
class RadioPreference:
    """A normalized uiwwand radio preference."""

    mode: str = "5gnr,lte"
    lte_bands: set[int] = field(default_factory=set)
    sa_bands: set[int] = field(default_factory=set)
    nsa_bands: set[int] = field(default_factory=set)
    net_selection: str = "automatic"

    @classmethod
    def from_uiwwand(cls, data: dict[str, Any]) -> "RadioPreference":
        """Create from get-radio-pref result data."""
        return cls(
            mode=str(data.get("mode", "5gnr,lte")),
            lte_bands=parse_band_list(data.get("lte_band")),
            sa_bands=parse_band_list(data.get("nr5g_sa_band")),
            nsa_bands=parse_band_list(data.get("nr5g_nsa_band")),
            net_selection=str(data.get("net_sel_pref", "automatic")),
        )

    def to_uiwwand(self, iccid: str) -> dict[str, Any]:
        """Create set-radio-pref params."""
        return {
            "iccid": iccid,
            "mode": self.mode,
            "lte_band": format_band_list(self.lte_bands),
            "nr5g_sa_band": format_band_list(self.sa_bands),
            "nr5g_nsa_band": format_band_list(self.nsa_bands),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible data."""
        return {
            "mode": self.mode,
            "lte_bands": sorted(self.lte_bands),
            "sa_bands": sorted(self.sa_bands),
            "nsa_bands": sorted(self.nsa_bands),
            "net_selection": self.net_selection,
        }

    def writable_dict(self) -> dict[str, Any]:
        """Return only fields which set-radio-pref can actually change."""
        return {
            "mode": self.mode,
            "lte_bands": sorted(self.lte_bands),
            "sa_bands": sorted(self.sa_bands),
            "nsa_bands": sorted(self.nsa_bands),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RadioPreference":
        """Deserialize persisted data."""
        return cls(
            mode=str(data.get("mode", "5gnr,lte")),
            lte_bands=parse_band_list(data.get("lte_bands")),
            sa_bands=parse_band_list(data.get("sa_bands")),
            nsa_bands=parse_band_list(data.get("nsa_bands")),
            net_selection=str(data.get("net_selection", "automatic")),
        )


@dataclass(slots=True)
class SimProfile:
    """Persistent settings and last state for an observed SIM."""

    sim_id: str
    iccid: str
    name: str
    spn: str = ""
    mcc: int | None = None
    mnc: int | None = None
    slot: int | None = None
    esim: bool = False
    sa_enabled: bool = True
    nsa_enabled: bool = True
    selected_lte_bands: set[int] = field(default_factory=set)
    selected_sa_bands: set[int] = field(default_factory=set)
    selected_nsa_bands: set[int] = field(default_factory=set)
    default_preference: RadioPreference = field(default_factory=RadioPreference)
    default_preference_placeholder: int | None = None
    last_good_preference: RadioPreference = field(default_factory=RadioPreference)
    last_good_preference_placeholder: int | None = None
    current_preference: RadioPreference | None = None
    current_preference_placeholder: int | None = None
    last_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible data."""
        data = asdict(self)
        data["selected_lte_bands"] = sorted(self.selected_lte_bands)
        data["selected_sa_bands"] = sorted(self.selected_sa_bands)
        data["selected_nsa_bands"] = sorted(self.selected_nsa_bands)
        data["default_preference"] = self.default_preference.to_dict()
        data["last_good_preference"] = self.last_good_preference.to_dict()
        data["current_preference"] = (
            self.current_preference.to_dict() if self.current_preference else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimProfile":
        """Deserialize persisted profile."""
        default_placeholder = data.get("default_preference_placeholder")
        last_good_placeholder = data.get("last_good_preference_placeholder")
        current_placeholder = data.get("current_preference_placeholder")
        current_preference = data.get("current_preference")
        return cls(
            sim_id=str(data["sim_id"]),
            iccid=str(data["iccid"]),
            name=str(data["name"]),
            spn=str(data.get("spn", "")),
            mcc=data.get("mcc"),
            mnc=data.get("mnc"),
            slot=data.get("slot"),
            esim=bool(data.get("esim", False)),
            sa_enabled=bool(data.get("sa_enabled", True)),
            nsa_enabled=bool(data.get("nsa_enabled", True)),
            selected_lte_bands=parse_band_list(data.get("selected_lte_bands")),
            selected_sa_bands=parse_band_list(data.get("selected_sa_bands")),
            selected_nsa_bands=parse_band_list(data.get("selected_nsa_bands")),
            default_preference=RadioPreference.from_dict(data.get("default_preference", {})),
            default_preference_placeholder=(
                int(default_placeholder) if default_placeholder is not None else None
            ),
            last_good_preference=RadioPreference.from_dict(data.get("last_good_preference", {})),
            last_good_preference_placeholder=(
                int(last_good_placeholder)
                if last_good_placeholder is not None
                else None
            ),
            current_preference=(
                RadioPreference.from_dict(current_preference)
                if isinstance(current_preference, dict)
                else None
            ),
            current_preference_placeholder=(
                int(current_placeholder) if current_placeholder is not None else None
            ),
            last_seen=data.get("last_seen"),
        )


@dataclass(slots=True)
class ModemSnapshot:
    """Combined result of one modem refresh."""

    sim_state: dict[str, Any]
    radio_preference: RadioPreference
    radio_status: dict[str, Any]
    modem_info: dict[str, str] = field(default_factory=dict)

