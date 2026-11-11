"""Privacy-conscious diagnostics for U5G Control."""

from __future__ import annotations

from copy import deepcopy
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import U5GRuntimeData
from .privacy import redact_diagnostics


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[U5GRuntimeData]
) -> dict[str, Any]:
    """Return diagnostics without credentials or location-bearing cell data."""
    coordinator = entry.runtime_data.coordinator
    snapshot = coordinator.data
    profiles = {
        sim_id: {
            "name": profile.name,
            "active": sim_id == coordinator.active_sim_id,
            "slot": profile.slot,
            "esim": profile.esim,
            "sa_enabled": profile.sa_enabled,
            "nsa_enabled": profile.nsa_enabled,
            "lte_bands": sorted(profile.selected_lte_bands),
            "sa_bands": sorted(profile.selected_sa_bands),
            "nsa_bands": sorted(profile.selected_nsa_bands),
            "last_seen": profile.last_seen,
        }
        for sim_id, profile in coordinator.profiles.items()
    }
    return {
        "modem": deepcopy(coordinator.modem_info),
        "active_sim_id": coordinator.active_sim_id,
        "radio_preference": snapshot.radio_preference.to_dict() if snapshot else None,
        "radio_status": redact_diagnostics(snapshot.radio_status) if snapshot else None,
        "profiles": profiles,
        "options": {
            "disabled_band": coordinator.disabled_band,
            "auto_reapply": coordinator.auto_reapply,
            "exposed_lte_bands": sorted(coordinator.exposed_lte_bands),
            "exposed_sa_bands": sorted(coordinator.exposed_sa_bands),
            "exposed_nsa_bands": sorted(coordinator.exposed_nsa_bands),
        },
    }

