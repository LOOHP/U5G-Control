"""Radio policy construction and validation."""

from __future__ import annotations

from dataclasses import replace

from .const import MODE_5G, MODE_5G_LTE, MODE_LTE
from .models import RadioPreference, SimProfile


class PolicyError(ValueError):
    """Raised when a requested radio policy would be invalid."""


def build_preference(profile: SimProfile, disabled_band: int) -> RadioPreference:
    """Build the complete modem preference for a SIM profile.

    The modem API does not reliably accept an empty SA/NSA mask. A supported,
    locally unused placeholder band is therefore used for disabled modes.
    """
    if profile.sa_enabled and profile.nsa_enabled:
        mode = MODE_5G_LTE
    elif profile.sa_enabled:
        mode = MODE_5G
    elif profile.nsa_enabled:
        mode = MODE_5G_LTE
    else:
        mode = MODE_LTE

    if profile.sa_enabled and not profile.selected_sa_bands:
        raise PolicyError("At least one SA band must be enabled while SA is enabled")
    if profile.nsa_enabled and not profile.selected_nsa_bands:
        raise PolicyError("At least one NSA band must be enabled while NSA is enabled")
    if profile.sa_enabled and disabled_band in profile.selected_sa_bands:
        raise PolicyError(
            f"n{disabled_band} is reserved as the disabled-mode placeholder"
        )
    if profile.nsa_enabled and disabled_band in profile.selected_nsa_bands:
        raise PolicyError(
            f"n{disabled_band} is reserved as the disabled-mode placeholder"
        )
    if mode != MODE_5G and not profile.selected_lte_bands:
        raise PolicyError("At least one LTE band must remain selected")

    return RadioPreference(
        mode=mode,
        lte_bands=set(profile.selected_lte_bands),
        sa_bands=set(profile.selected_sa_bands) if profile.sa_enabled else {disabled_band},
        nsa_bands=set(profile.selected_nsa_bands) if profile.nsa_enabled else {disabled_band},
        net_selection="automatic",
    )


def infer_mode_flags(preference: RadioPreference, disabled_band: int) -> tuple[bool, bool]:
    """Infer SA/NSA enable flags from a live modem preference."""
    tokens = {item.strip() for item in preference.mode.split(",")}
    has_5g = MODE_5G in tokens
    has_lte = MODE_LTE in tokens
    sa_enabled = has_5g and preference.sa_bands != {disabled_band}
    nsa_enabled = has_5g and has_lte and preference.nsa_bands != {disabled_band}
    return sa_enabled, nsa_enabled


def initial_sim_radio_state(
    preference: RadioPreference,
    preference_placeholder: int,
    disabled_band: int,
    fallback_sa_bands: set[int],
    fallback_nsa_bands: set[int],
) -> tuple[bool, bool, set[int], set[int], set[int]]:
    """Build managed state for a SIM from the modem-wide baseline."""
    sa_enabled, nsa_enabled = infer_mode_flags(
        preference, preference_placeholder
    )
    selected_sa_bands = set(preference.sa_bands) - {disabled_band}
    selected_nsa_bands = set(preference.nsa_bands) - {disabled_band}
    if not selected_sa_bands:
        sa_enabled = False
        selected_sa_bands = set(fallback_sa_bands)
    if not selected_nsa_bands:
        nsa_enabled = False
        selected_nsa_bands = set(fallback_nsa_bands)
    return (
        sa_enabled,
        nsa_enabled,
        set(preference.lte_bands),
        selected_sa_bands,
        selected_nsa_bands,
    )


def should_apply_sim_profile(
    *,
    is_new: bool,
    previous_sim_id: str | None,
    current_sim_id: str,
    auto_reapply: bool,
) -> bool:
    """Return whether live modem settings must be replaced by this SIM's policy."""
    return (
        is_new
        or (
            previous_sim_id is not None
            and previous_sim_id != current_sim_id
        )
        or auto_reapply
    )


def with_band(profile: SimProfile, architecture: str, band: int, enabled: bool) -> SimProfile:
    """Return a profile with one band toggled."""
    if architecture not in {"lte", "sa", "nsa"}:
        raise PolicyError(f"Unsupported architecture: {architecture}")

    attr = f"selected_{architecture}_bands"
    bands = set(getattr(profile, attr))
    if enabled:
        bands.add(band)
    else:
        bands.discard(band)

    if not bands:
        lte_active = profile.nsa_enabled or not profile.sa_enabled
        active = (architecture == "lte" and lte_active) or (
            architecture == "sa" and profile.sa_enabled
        ) or (architecture == "nsa" and profile.nsa_enabled)
        if active:
            raise PolicyError(f"Cannot disable the final active {architecture.upper()} band")

    return replace(profile, **{attr: bands})

