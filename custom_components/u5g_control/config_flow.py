"""Config and options flows for U5G Control."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, selector

from .api import ProbeResult, U5GApiError, U5GAuthenticationError, U5GClient
from .const import (
    CONF_AUTO_REAPPLY,
    CONF_DISABLED_BAND,
    CONF_FORGET_SIMS,
    CONF_HOST_KEY,
    CONF_LTE_BANDS,
    CONF_NSA_BANDS,
    CONF_SA_BANDS,
    CONF_SCAN_INTERVAL,
    DEFAULT_DISABLED_BAND,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _band_selector(bands: set[int], prefix: str) -> selector.SelectSelector:
    options = [
        {"value": str(band), "label": f"{prefix}{band}"}
        for band in sorted(bands)
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _single_band_selector(
    bands: set[int], prefix: str
) -> selector.SelectSelector:
    """Build a single-choice band dropdown with friendly band names."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": str(band), "label": f"{prefix}{band}"}
                for band in sorted(bands)
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


class U5GControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one physical modem."""

    VERSION = 1

    def __init__(self) -> None:
        self._connection_data: dict[str, Any] = {}
        self._probe: ProbeResult | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect SSH connection details and probe the modem."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = U5GClient(
                host=user_input[CONF_HOST],
                port=user_input[CONF_PORT],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                self._probe = await client.async_probe()
            except U5GAuthenticationError:
                errors["base"] = "invalid_auth"
            except U5GApiError:
                _LOGGER.exception("Unable to probe U5G modem")
                errors["base"] = "cannot_connect"
            else:
                self._connection_data = dict(user_input)
                modem_id = self._probe.info.get("mac")
                if not modem_id:
                    errors["base"] = "cannot_identify"
                else:
                    await self.async_set_unique_id(modem_id.lower())
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: user_input[CONF_HOST],
                            CONF_PORT: user_input[CONF_PORT],
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            "modem_info": self._probe.info,
                        }
                    )
                    return await self.async_step_placeholder()
            finally:
                await client.async_close()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(int, vol.Range(min=1, max=65535)),
                vol.Required(CONF_USERNAME, default="ui"): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_placeholder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the NR band used as the disabled-mode placeholder."""
        assert self._probe is not None
        preference = self._probe.snapshot.radio_preference
        available_nr = preference.sa_bands | preference.nsa_bands
        if not available_nr:
            available_nr = {DEFAULT_DISABLED_BAND}
        default_band = (
            DEFAULT_DISABLED_BAND
            if DEFAULT_DISABLED_BAND in available_nr
            else max(available_nr)
        )

        if user_input is not None:
            self._connection_data[CONF_DISABLED_BAND] = int(
                user_input[CONF_DISABLED_BAND]
            )
            return await self.async_step_bands()

        return self.async_show_form(
            step_id="placeholder",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DISABLED_BAND, default=str(default_band)
                    ): _single_band_selector(available_nr, "n")
                }
            ),
            description_placeholders={
                "model": self._probe.info.get("model", "U5G modem")
            },
        )

    async def async_step_bands(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the band switches to expose."""
        assert self._probe is not None
        preference = self._probe.snapshot.radio_preference
        disabled_band = int(self._connection_data[CONF_DISABLED_BAND])
        available_sa = preference.sa_bands - {disabled_band}
        available_nsa = preference.nsa_bands - {disabled_band}
        if user_input is not None:
            data = {
                **self._connection_data,
                CONF_HOST_KEY: self._probe.host_key,
                "modem_info": self._probe.info,
                CONF_LTE_BANDS: user_input[CONF_LTE_BANDS],
                CONF_SA_BANDS: [
                    value for value in user_input[CONF_SA_BANDS]
                    if int(value) != disabled_band
                ],
                CONF_NSA_BANDS: [
                    value for value in user_input[CONF_NSA_BANDS]
                    if int(value) != disabled_band
                ],
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_AUTO_REAPPLY: False,
            }
            title = self._probe.info.get("hostname") or self._probe.info.get("model") or "U5G Modem"
            return self.async_create_entry(title=title, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_LTE_BANDS, default=[]): _band_selector(
                    preference.lte_bands, "b"
                ),
                vol.Required(CONF_SA_BANDS, default=[]): _band_selector(
                    available_sa, "n"
                ),
                vol.Required(CONF_NSA_BANDS, default=[]): _band_selector(
                    available_nsa, "n"
                ),
            }
        )
        return self.async_show_form(
            step_id="bands",
            data_schema=schema,
            description_placeholders={
                "model": self._probe.info.get("model", "U5G modem"),
                "disabled_band": f"n{disabled_band}",
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after SSH credentials stop working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and save replacement SSH credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = U5GClient(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                host_key=entry.data[CONF_HOST_KEY],
            )
            try:
                await client.async_get_snapshot()
                modem_info = await client.async_get_info()
            except U5GAuthenticationError:
                errors["base"] = "invalid_auth"
            except U5GApiError:
                _LOGGER.exception("Unable to reauthenticate with U5G modem")
                errors["base"] = "cannot_connect"
            else:
                modem_id = modem_info.get("mac")
                if not modem_id:
                    errors["base"] = "cannot_identify"
                else:
                    await self.async_set_unique_id(modem_id.lower())
                    self._abort_if_unique_id_mismatch(reason="wrong_modem")
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            "modem_info": modem_info,
                        },
                    )
            finally:
                await client.async_close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=entry.data[CONF_USERNAME],
                    ): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "U5GOptionsFlow":
        return U5GOptionsFlow()


class U5GOptionsFlow(OptionsFlow):
    """Reconfigure exposed bands and remembered SIMs."""

    def __init__(self) -> None:
        self._current: dict[str, Any] = {}
        self._pending: dict[str, Any] = {}
        self._known_lte: set[int] = set()
        self._known_sa: set[int] = set()
        self._known_nsa: set[int] = set()
        self._coordinator: Any = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        runtime = getattr(entry, "runtime_data", None)
        coordinator = runtime.coordinator if runtime else None
        current = {**entry.data, **entry.options}

        known_lte = set(coordinator.exposed_lte_bands if coordinator else current.get(CONF_LTE_BANDS, []))
        known_sa = set(coordinator.exposed_sa_bands if coordinator else current.get(CONF_SA_BANDS, []))
        known_nsa = set(coordinator.exposed_nsa_bands if coordinator else current.get(CONF_NSA_BANDS, []))
        current_disabled = int(
            current.get(CONF_DISABLED_BAND, DEFAULT_DISABLED_BAND)
        )
        if coordinator and coordinator.data:
            pref = coordinator.data.radio_preference
            known_lte |= pref.lte_bands
            known_sa |= pref.sa_bands
            known_nsa |= pref.nsa_bands

        if user_input is not None:
            user_input[CONF_DISABLED_BAND] = int(user_input[CONF_DISABLED_BAND])
            user_input.setdefault(
                CONF_SCAN_INTERVAL,
                int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            )
            self._current = current
            self._pending = dict(user_input)
            self._known_lte = {int(x) for x in known_lte}
            self._known_sa = {int(x) for x in known_sa}
            self._known_nsa = {int(x) for x in known_nsa}
            self._coordinator = coordinator
            return await self.async_step_bands()

        schema_values: dict[Any, Any] = {
            vol.Required(
                CONF_DISABLED_BAND,
                default=str(current_disabled),
            ): _single_band_selector(
                {int(x) for x in known_sa | known_nsa} | {current_disabled}, "n"
            ),
            vol.Required(
                CONF_AUTO_REAPPLY,
                default=bool(current.get(CONF_AUTO_REAPPLY, False)),
            ): bool,
        }
        if self.show_advanced_options:
            schema_values[
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                )
            ] = vol.All(int, vol.Range(min=10, max=600))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_values))

    async def async_step_bands(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose exposed bands after the disabled NR band is known."""
        disabled_band = int(self._pending[CONF_DISABLED_BAND])
        allowed_sa = self._known_sa - {disabled_band}
        allowed_nsa = self._known_nsa - {disabled_band}

        if user_input is not None:
            forgotten = list(user_input.pop(CONF_FORGET_SIMS, []))
            updated = {
                **self._pending,
                CONF_LTE_BANDS: user_input[CONF_LTE_BANDS],
                CONF_SA_BANDS: [
                    value for value in user_input[CONF_SA_BANDS]
                    if int(value) != disabled_band
                ],
                CONF_NSA_BANDS: [
                    value for value in user_input[CONF_NSA_BANDS]
                    if int(value) != disabled_band
                ],
            }
            old_disabled_band = int(
                self._current.get(CONF_DISABLED_BAND, DEFAULT_DISABLED_BAND)
            )
            if self._coordinator and disabled_band != old_disabled_band:
                await self._coordinator.async_migrate_disabled_band(
                    old_disabled_band,
                    disabled_band,
                    {int(value) for value in updated[CONF_SA_BANDS]},
                    {int(value) for value in updated[CONF_NSA_BANDS]},
                )
            self._cleanup_removed_band_entities(self.config_entry, self._current, updated)
            if self._coordinator and forgotten:
                await self._coordinator.async_forget_profiles(forgotten)
                self._cleanup_forgotten(
                    self.config_entry, self._coordinator.modem_id, forgotten
                )
            return self.async_create_entry(title="", data=updated)

        sim_options: list[dict[str, str]] = []
        if self._coordinator:
            sim_options = [
                {"value": sim_id, "label": profile.name}
                for sim_id, profile in self._coordinator.profiles.items()
                if sim_id != self._coordinator.active_sim_id
            ]

        schema_values: dict[Any, Any] = {
            vol.Required(
                CONF_LTE_BANDS,
                default=[str(v) for v in sorted(
                    {int(x) for x in self._current.get(CONF_LTE_BANDS, [])}
                )],
            ): _band_selector(self._known_lte, "b"),
            vol.Required(
                CONF_SA_BANDS,
                default=[str(v) for v in sorted(
                    {int(x) for x in self._current.get(CONF_SA_BANDS, [])} & allowed_sa
                )],
            ): _band_selector(allowed_sa, "n"),
            vol.Required(
                CONF_NSA_BANDS,
                default=[str(v) for v in sorted(
                    {int(x) for x in self._current.get(CONF_NSA_BANDS, [])} & allowed_nsa
                )],
            ): _band_selector(allowed_nsa, "n"),
        }
        if sim_options:
            schema_values[vol.Optional(CONF_FORGET_SIMS, default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=sim_options, multiple=True)
            )
        return self.async_show_form(
            step_id="bands",
            data_schema=vol.Schema(schema_values),
            description_placeholders={"disabled_band": f"n{disabled_band}"},
        )

    def _cleanup_forgotten(
        self, entry: ConfigEntry, modem_id: str, sim_ids: list[str]
    ) -> None:
        entity_registry = er.async_get(self.hass)
        for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
            if any(f":{sim_id}:" in entity.unique_id for sim_id in sim_ids):
                entity_registry.async_remove(entity.entity_id)

        device_registry = dr.async_get(self.hass)
        for sim_id in sim_ids:
            device = device_registry.async_get_device(identifiers={(DOMAIN, f"{modem_id}:sim:{sim_id}")})
            if device:
                device_registry.async_remove_device(device.id)

    def _cleanup_removed_band_entities(
        self, entry: ConfigEntry, current: dict[str, Any], updated: dict[str, Any]
    ) -> None:
        """Remove registry entries for band switches no longer exposed."""
        entity_registry = er.async_get(self.hass)
        removed: set[tuple[str, int]] = set()
        for architecture, key in (
            ("lte", CONF_LTE_BANDS),
            ("sa", CONF_SA_BANDS),
            ("nsa", CONF_NSA_BANDS),
        ):
            before = {int(value) for value in current.get(key, [])}
            after = {int(value) for value in updated.get(key, [])}
            removed.update((architecture, band) for band in before - after)
        removed_mode_switches = {
            architecture
            for architecture, key in (
                ("sa", CONF_SA_BANDS),
                ("nsa", CONF_NSA_BANDS),
            )
            if not updated.get(key, [])
        }
        for entity in list(er.async_entries_for_config_entry(entity_registry, entry.entry_id)):
            band_removed = any(
                entity.unique_id.endswith(f":switch:{architecture}:{band}")
                for architecture, band in removed
            )
            mode_removed = any(
                entity.unique_id.endswith(f":switch:enable_{architecture}")
                for architecture in removed_mode_switches
            )
            if band_removed or mode_removed:
                entity_registry.async_remove(entity.entity_id)

