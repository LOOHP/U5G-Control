"""Mode and band switches for U5G Control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import U5GRuntimeData
from .coordinator import U5GCoordinator
from .entity import U5GSimEntity


class U5GModeSwitch(U5GSimEntity, SwitchEntity):
    """Allow one 5G architecture for a SIM profile."""

    def __init__(self, coordinator: U5GCoordinator, sim_id: str, architecture: str) -> None:
        super().__init__(coordinator, sim_id, f"switch:enable_{architecture}")
        self.architecture = architecture
        self._pending_is_on: bool | None = None
        self._pending_token: object | None = None
        self._attr_name = f"Enable 5G {architecture.upper()}"
        self._attr_icon = "mdi:signal-5g"

    @property
    def is_on(self) -> bool:
        if self._pending_is_on is not None:
            return self._pending_is_on
        return bool(getattr(self.coordinator.profile(self.sim_id), f"{self.architecture}_enabled"))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._async_set_state(False)

    async def _async_set_state(self, enabled: bool) -> None:
        """Keep the requested state visible while the serialized write completes."""
        token = object()
        self._pending_token = token
        self._pending_is_on = enabled
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_mode(
                self.sim_id, self.architecture, enabled
            )
        finally:
            if self._pending_token is token:
                self._pending_token = None
                self._pending_is_on = None
                self.async_write_ha_state()


class U5GBandSwitch(U5GSimEntity, SwitchEntity):
    """Toggle one LTE, SA, or NSA band."""

    def __init__(
        self, coordinator: U5GCoordinator, sim_id: str, architecture: str, band: int
    ) -> None:
        super().__init__(coordinator, sim_id, f"switch:{architecture}:{band}")
        self.architecture = architecture
        self.band = band
        self._pending_is_on: bool | None = None
        self._pending_token: object | None = None
        prefix = "b" if architecture == "lte" else "n"
        self._attr_name = f"{architecture.upper()} {prefix}{band}"
        self._attr_icon = "mdi:radio-tower"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        profile = self.coordinator.profile(self.sim_id)
        if self.architecture == "sa":
            return profile.sa_enabled
        if self.architecture == "nsa":
            return profile.nsa_enabled
        return True

    @property
    def is_on(self) -> bool:
        if self._pending_is_on is not None:
            return self._pending_is_on
        bands = getattr(self.coordinator.profile(self.sim_id), f"selected_{self.architecture}_bands")
        return self.band in bands

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._async_set_state(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._async_set_state(False)

    async def _async_set_state(self, enabled: bool) -> None:
        """Keep the requested state visible while the serialized write completes."""
        token = object()
        self._pending_token = token
        self._pending_is_on = enabled
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_band(
                self.sim_id, self.architecture, self.band, enabled
            )
        finally:
            if self._pending_token is token:
                self._pending_token = None
                self._pending_is_on = None
                self.async_write_ha_state()


def _sim_switches(coordinator: U5GCoordinator, sim_id: str) -> list[SwitchEntity]:
    result: list[SwitchEntity] = []
    if coordinator.exposed_sa_bands:
        result.append(U5GModeSwitch(coordinator, sim_id, "sa"))
    if coordinator.exposed_nsa_bands:
        result.append(U5GModeSwitch(coordinator, sim_id, "nsa"))
    for architecture, bands in (
        ("lte", coordinator.exposed_lte_bands),
        ("sa", coordinator.exposed_sa_bands),
        ("nsa", coordinator.exposed_nsa_bands),
    ):
        result.extend(U5GBandSwitch(coordinator, sim_id, architecture, band) for band in sorted(bands))
    return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[U5GRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def add_new_sims() -> None:
        new = [sim_id for sim_id in coordinator.profiles if sim_id not in known]
        if not new:
            return
        for sim_id in new:
            known.add(sim_id)
        async_add_entities([entity for sim_id in new for entity in _sim_switches(coordinator, sim_id)])

    add_new_sims()
    entry.async_on_unload(coordinator.async_add_listener(add_new_sims))

