"""Home Assistant update coordinator for one U5G modem hub."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import U5GApiError, U5GAuthenticationError, U5GClient
from .const import (
    CONF_AUTO_REAPPLY,
    CONF_DISABLED_BAND,
    CONF_LTE_BANDS,
    CONF_NSA_BANDS,
    CONF_SA_BANDS,
    CONF_SCAN_INTERVAL,
    DEFAULT_DISABLED_BAND,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODE_LTE,
    STORE_KEY_PREFIX,
    STORE_VERSION,
)
from .models import (
    ModemSnapshot,
    RadioPreference,
    SimProfile,
    sim_display_name,
    sim_identifier,
)
from .policy import (
    PolicyError,
    build_preference,
    infer_mode_flags,
    initial_sim_radio_state,
    should_apply_sim_profile,
    with_band,
)

_LOGGER = logging.getLogger(__name__)
_LAST_SEEN_SAVE_INTERVAL = timedelta(hours=1)


class U5GCoordinator(DataUpdateCoordinator[ModemSnapshot]):
    """Coordinate one physical modem and its remembered SIM children."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: U5GClient,
        modem_id: str,
        modem_info: dict[str, str],
    ) -> None:
        options = {**entry.data, **entry.options}
        interval = int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{modem_id}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.entry = entry
        self.client = client
        self.modem_id = modem_id
        self.modem_info = modem_info
        self.disabled_band = int(options.get(CONF_DISABLED_BAND, DEFAULT_DISABLED_BAND))
        self.auto_reapply = bool(options.get(CONF_AUTO_REAPPLY, False))
        self.exposed_lte_bands = {int(value) for value in options.get(CONF_LTE_BANDS, [])}
        self.exposed_sa_bands = {int(value) for value in options.get(CONF_SA_BANDS, [])}
        self.exposed_nsa_bands = {int(value) for value in options.get(CONF_NSA_BANDS, [])}
        self.exposed_sa_bands.discard(self.disabled_band)
        self.exposed_nsa_bands.discard(self.disabled_band)
        self.profiles: dict[str, SimProfile] = {}
        self._last_seen_persisted: dict[str, Any] = {}
        self._modem_default_preference: RadioPreference | None = None
        self._modem_default_preference_placeholder: int | None = None
        self._last_active_sim_id: str | None = None
        self.active_sim_id: str | None = None
        self._write_lock = asyncio.Lock()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{STORE_KEY_PREFIX}.{entry.entry_id}"
        )

    async def async_load(self) -> None:
        """Load remembered SIM profiles."""
        stored = await self._store.async_load() or {}
        self.profiles = {
            sim_id: SimProfile.from_dict(value)
            for sim_id, value in stored.get("profiles", {}).items()
        }
        stored_default = stored.get("modem_default_preference")
        if isinstance(stored_default, dict):
            self._modem_default_preference = RadioPreference.from_dict(
                stored_default
            )
            stored_placeholder = stored.get(
                "modem_default_preference_placeholder"
            )
            self._modem_default_preference_placeholder = (
                int(stored_placeholder)
                if stored_placeholder is not None
                else self.disabled_band
            )
        elif self.profiles:
            # Backfill installations created before the hub baseline was
            # stored explicitly. The oldest remembered default was captured
            # before that SIM's first managed write.
            first_profile = next(iter(self.profiles.values()))
            self._modem_default_preference = self._copy_preference(
                first_profile.default_preference
            )
            self._modem_default_preference_placeholder = (
                first_profile.default_preference_placeholder
                or self.disabled_band
            )
        self._last_active_sim_id = stored.get("last_active_sim_id")
        if self._last_active_sim_id is None and self.profiles:
            latest_profile = max(
                self.profiles.values(), key=lambda profile: profile.last_seen or ""
            )
            self._last_active_sim_id = latest_profile.sim_id
        self._last_seen_persisted = {
            sim_id: parsed
            for sim_id, profile in self.profiles.items()
            if profile.last_seen
            and (parsed := dt_util.parse_datetime(profile.last_seen)) is not None
        }

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "profiles": {
                    key: value.to_dict() for key, value in self.profiles.items()
                },
                "modem_default_preference": (
                    self._modem_default_preference.to_dict()
                    if self._modem_default_preference
                    else None
                ),
                "modem_default_preference_placeholder": (
                    self._modem_default_preference_placeholder
                ),
                "last_active_sim_id": self._last_active_sim_id,
            }
        )
        self._last_seen_persisted = {
            sim_id: parsed
            for sim_id, profile in self.profiles.items()
            if profile.last_seen
            and (parsed := dt_util.parse_datetime(profile.last_seen)) is not None
        }

    def is_active(self, sim_id: str) -> bool:
        """Return whether a child SIM is currently active."""
        return sim_id == self.active_sim_id

    def profile(self, sim_id: str) -> SimProfile:
        """Return a profile or raise an HA-friendly error."""
        try:
            return self.profiles[sim_id]
        except KeyError as err:
            raise HomeAssistantError("The remembered SIM profile no longer exists") from err

    async def _async_update_data(self) -> ModemSnapshot:
        try:
            async with self._write_lock:
                snapshot = await self.client.async_get_snapshot()
                return await self._async_reconcile(snapshot)
        except U5GAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except U5GApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_reconcile(self, snapshot: ModemSnapshot) -> ModemSnapshot:
        sim = snapshot.sim_state
        iccid = str(sim.get("iccid", ""))
        if not iccid or not sim.get("active", False):
            self.active_sim_id = None
            return snapshot

        current_id = sim_identifier(self.modem_id, iccid)
        previous_sim_id = self._last_active_sim_id
        sim_changed = (
            previous_sim_id is not None and previous_sim_id != current_id
        )
        self.active_sim_id = current_id
        profile = self.profiles.get(current_id)
        is_new = profile is None
        baseline_created = False
        persisted_before = None if is_new else profile.to_dict()
        if persisted_before is not None:
            persisted_before.pop("last_seen", None)
        if profile is None:
            if self._modem_default_preference is None:
                self._modem_default_preference = self._copy_preference(
                    snapshot.radio_preference
                )
                self._modem_default_preference_placeholder = self.disabled_band
                baseline_created = True
            initial_preference = self._copy_preference(
                self._modem_default_preference
            )
            initial_placeholder = (
                self._modem_default_preference_placeholder
                or self.disabled_band
            )
            (
                sa_enabled,
                nsa_enabled,
                selected_lte_bands,
                selected_sa_bands,
                selected_nsa_bands,
            ) = initial_sim_radio_state(
                initial_preference,
                initial_placeholder,
                self.disabled_band,
                self.exposed_sa_bands,
                self.exposed_nsa_bands,
            )
            profile = SimProfile(
                sim_id=current_id,
                iccid=iccid,
                name=sim_display_name(sim.get("spn"), sim.get("mcc"), sim.get("mnc"), iccid),
                spn=str(sim.get("spn", "")),
                mcc=sim.get("mcc"),
                mnc=sim.get("mnc"),
                slot=sim.get("slot"),
                esim=bool(sim.get("esim", False)),
                sa_enabled=sa_enabled,
                nsa_enabled=nsa_enabled,
                selected_lte_bands=selected_lte_bands,
                selected_sa_bands=selected_sa_bands,
                selected_nsa_bands=selected_nsa_bands,
                default_preference=self._copy_preference(initial_preference),
                default_preference_placeholder=initial_placeholder,
                last_good_preference=self._copy_preference(initial_preference),
                last_good_preference_placeholder=initial_placeholder,
                current_preference=self._copy_preference(initial_preference),
                current_preference_placeholder=initial_placeholder,
            )
            self.profiles[current_id] = profile
        else:
            profile.spn = str(sim.get("spn", profile.spn))
            profile.mcc = sim.get("mcc", profile.mcc)
            profile.mnc = sim.get("mnc", profile.mnc)
            profile.slot = sim.get("slot", profile.slot)
            profile.esim = bool(sim.get("esim", profile.esim))
            if not self.auto_reapply and not sim_changed:
                self._sync_profile_from_live(profile, snapshot.radio_preference)
        now = dt_util.now()
        profile.last_seen = now.isoformat()
        persisted_after = profile.to_dict()
        persisted_after.pop("last_seen", None)
        last_seen_persisted = self._last_seen_persisted.get(current_id)
        last_seen_due = (
            last_seen_persisted is None
            or now - last_seen_persisted >= _LAST_SEEN_SAVE_INTERVAL
        )
        should_apply_profile = should_apply_sim_profile(
            is_new=is_new,
            previous_sim_id=previous_sim_id,
            current_sim_id=current_id,
            auto_reapply=self.auto_reapply,
        )
        preference_applied = False
        if should_apply_profile:
            try:
                desired = build_preference(profile, self.disabled_band)
            except PolicyError:
                desired = None
            if (
                desired is not None
                and desired.writable_dict()
                != snapshot.radio_preference.writable_dict()
            ):
                reason = "SIM change" if is_new or sim_changed else "configuration drift"
                _LOGGER.info(
                    "Applying saved radio policy for %s after %s",
                    profile.name,
                    reason,
                )
                await self.client.async_set_preference(profile.iccid, desired)
                profile.current_preference = self._copy_preference(desired)
                profile.current_preference_placeholder = self.disabled_band
                preference_applied = True
                snapshot = await self.client.async_get_snapshot()
        active_changed = self._last_active_sim_id != current_id
        self._last_active_sim_id = current_id
        if (
            is_new
            or baseline_created
            or active_changed
            or preference_applied
            or persisted_before != persisted_after
            or last_seen_due
        ):
            await self._async_save()
        return snapshot

    @staticmethod
    def _copy_preference(preference):
        """Deep-copy a preference without sharing mutable band sets."""
        return type(preference).from_dict(preference.to_dict())

    def _sync_profile_from_live(self, profile: SimProfile, preference) -> None:
        """Adopt externally changed live settings when enforcement is disabled."""
        placeholder = self._placeholder_for_preference(profile, preference)
        self._apply_preference_to_profile(profile, preference, placeholder)
        profile.current_preference = self._copy_preference(preference)
        profile.current_preference_placeholder = placeholder

    def _placeholder_for_preference(self, profile: SimProfile, preference) -> int:
        """Return the placeholder which gives a captured preference its meaning."""
        placeholder = self.disabled_band
        if (
            profile.current_preference is not None
            and preference.writable_dict()
            == profile.current_preference.writable_dict()
            and profile.current_preference_placeholder is not None
        ):
            placeholder = profile.current_preference_placeholder
        elif (
            preference.writable_dict()
            == profile.default_preference.writable_dict()
            and profile.default_preference_placeholder is not None
        ):
            placeholder = profile.default_preference_placeholder
        elif (
            preference.writable_dict()
            == profile.last_good_preference.writable_dict()
            and profile.last_good_preference_placeholder is not None
        ):
            placeholder = profile.last_good_preference_placeholder
        return placeholder

    def _apply_preference_to_profile(
        self, profile: SimProfile, preference, placeholder: int
    ) -> None:
        """Update managed profile state after a preference has been applied."""
        sa_enabled, nsa_enabled = infer_mode_flags(preference, placeholder)
        profile.sa_enabled = sa_enabled
        profile.nsa_enabled = nsa_enabled
        profile.selected_lte_bands = set(preference.lte_bands)
        if sa_enabled:
            profile.selected_sa_bands = set(preference.sa_bands) - {
                self.disabled_band
            }
        if nsa_enabled:
            profile.selected_nsa_bands = set(preference.nsa_bands) - {
                self.disabled_band
            }
            if not profile.selected_nsa_bands:
                profile.nsa_enabled = False
        if sa_enabled and not profile.selected_sa_bands:
            profile.sa_enabled = False

    async def async_set_mode(self, sim_id: str, architecture: str, enabled: bool) -> None:
        """Enable or disable SA/NSA for the active SIM."""
        if not self.is_active(sim_id):
            raise HomeAssistantError("This SIM is not active")
        if architecture not in {"sa", "nsa"}:
            raise HomeAssistantError("Unknown radio architecture")
        profile = self.profile(sim_id)
        changed = replace(profile, **{f"{architecture}_enabled": enabled})
        refresh_registration = (
            architecture == "sa"
            and enabled
            and not profile.sa_enabled
            and profile.nsa_enabled
        )
        await self._async_apply_profile(
            changed, refresh_registration=refresh_registration
        )

    async def async_set_band(
        self, sim_id: str, architecture: str, band: int, enabled: bool
    ) -> None:
        """Toggle one band and atomically apply the complete mask."""
        if not self.is_active(sim_id):
            raise HomeAssistantError("This SIM is not active")
        if architecture in {"sa", "nsa"} and band == self.disabled_band:
            raise HomeAssistantError(
                f"n{band} is reserved as the disabled-mode placeholder"
            )
        try:
            changed = with_band(self.profile(sim_id), architecture, band, enabled)
        except PolicyError as err:
            raise HomeAssistantError(str(err)) from err
        await self._async_apply_profile(changed)

    async def _async_apply_profile(
        self,
        changed: SimProfile,
        *,
        refresh_registration: bool = False,
    ) -> None:
        async with self._write_lock:
            try:
                preference = build_preference(changed, self.disabled_band)
            except PolicyError as err:
                raise HomeAssistantError(str(err)) from err

            old_profile = self.profile(changed.sim_id)
            self.profiles[changed.sim_id] = changed
            self.async_update_listeners()
            parked_preference = None
            try:
                current = await self.client.async_get_snapshot()
                changed.last_good_preference = self._copy_preference(
                    current.radio_preference
                )
                changed.last_good_preference_placeholder = (
                    self._placeholder_for_preference(
                        old_profile, current.radio_preference
                    )
                )
                if refresh_registration:
                    parked_preference = replace(
                        preference,
                        mode=MODE_LTE,
                        sa_bands={self.disabled_band},
                        nsa_bands={self.disabled_band},
                    )
                    await self.client.async_set_preference(
                        changed.iccid, parked_preference
                    )
                    # uiwwand acknowledges before registration state has fully
                    # settled. Give the modem a moment to leave the old NSA
                    # session before restoring the requested complete policy.
                    await asyncio.sleep(1)
                await self.client.async_set_preference(changed.iccid, preference)
            except BaseException as err:
                if parked_preference is not None:
                    try:
                        await self.client.async_set_preference(
                            changed.iccid, current.radio_preference
                        )
                    except U5GApiError:
                        _LOGGER.exception(
                            "Unable to restore radio preference after failed "
                            "SA registration refresh"
                        )
                self.profiles[changed.sim_id] = old_profile
                self.async_update_listeners()
                if isinstance(err, U5GApiError):
                    raise HomeAssistantError(str(err)) from err
                raise
            changed.current_preference = self._copy_preference(preference)
            changed.current_preference_placeholder = self.disabled_band
            await self._async_save()
        await self.async_request_refresh()

    async def async_restore_default(self, sim_id: str) -> None:
        """Restore the preference captured when the SIM was first observed."""
        if not self.is_active(sim_id):
            raise HomeAssistantError("This SIM is not active")
        profile = self.profile(sim_id)
        async with self._write_lock:
            try:
                current = await self.client.async_get_snapshot()
                previous = self._copy_preference(current.radio_preference)
                previous_placeholder = self._placeholder_for_preference(
                    profile, previous
                )
                target = self._copy_preference(profile.default_preference)
                target_placeholder = (
                    profile.default_preference_placeholder or self.disabled_band
                )
                await self.client.async_set_preference(profile.iccid, target)
            except U5GApiError as err:
                raise HomeAssistantError(str(err)) from err
            profile.last_good_preference = previous
            profile.last_good_preference_placeholder = previous_placeholder
            profile.current_preference = self._copy_preference(target)
            profile.current_preference_placeholder = target_placeholder
            self._apply_preference_to_profile(
                profile, target, target_placeholder
            )
            await self._async_save()
        await self.async_request_refresh()

    async def async_restore_previous(self, sim_id: str) -> None:
        """Restore the last preference before the most recent write."""
        if not self.is_active(sim_id):
            raise HomeAssistantError("This SIM is not active")
        profile = self.profile(sim_id)
        async with self._write_lock:
            try:
                current = await self.client.async_get_snapshot()
                previous = self._copy_preference(current.radio_preference)
                previous_placeholder = self._placeholder_for_preference(
                    profile, previous
                )
                target = self._copy_preference(profile.last_good_preference)
                target_placeholder = (
                    profile.last_good_preference_placeholder or self.disabled_band
                )
                await self.client.async_set_preference(profile.iccid, target)
            except U5GApiError as err:
                raise HomeAssistantError(str(err)) from err
            profile.last_good_preference = previous
            profile.last_good_preference_placeholder = previous_placeholder
            profile.current_preference = self._copy_preference(target)
            profile.current_preference_placeholder = target_placeholder
            self._apply_preference_to_profile(
                profile, target, target_placeholder
            )
            await self._async_save()
        await self.async_request_refresh()

    async def async_forget_profiles(self, sim_ids: list[str]) -> None:
        """Forget inactive SIM profiles."""
        async with self._write_lock:
            for sim_id in sim_ids:
                if sim_id != self.active_sim_id:
                    self.profiles.pop(sim_id, None)
            await self._async_save()

    async def async_migrate_disabled_band(
        self,
        old_band: int,
        new_band: int,
        replacement_sa_bands: set[int],
        replacement_nsa_bands: set[int],
    ) -> None:
        """Normalize managed selections without modifying exact restore points."""
        if old_band == new_band:
            return
        async with self._write_lock:
            replacement_sa_bands = set(replacement_sa_bands) - {new_band}
            replacement_nsa_bands = set(replacement_nsa_bands) - {new_band}
            for profile in self.profiles.values():
                profile.selected_sa_bands -= {old_band, new_band}
                profile.selected_nsa_bands -= {old_band, new_band}
                if not profile.selected_sa_bands:
                    profile.selected_sa_bands = set(replacement_sa_bands)
                if not profile.selected_nsa_bands:
                    profile.selected_nsa_bands = set(replacement_nsa_bands)
                if profile.sa_enabled and not profile.selected_sa_bands:
                    profile.sa_enabled = False
                if profile.nsa_enabled and not profile.selected_nsa_bands:
                    profile.nsa_enabled = False
            await self._async_save()

