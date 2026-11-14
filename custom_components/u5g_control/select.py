"""SIM selection for U5G Control."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import U5GRuntimeData
from .coordinator import U5GCoordinator
from .entity import U5GHubEntity
from .models import SimProfile


class U5GPrimarySimSelect(U5GHubEntity, SelectEntity):
    """Select the preferred SIM while preserving automatic failover."""

    _attr_name = "Primary SIM"
    _attr_icon = "mdi:sim"

    def __init__(self, coordinator: U5GCoordinator) -> None:
        super().__init__(coordinator, "select:active_sim")
        self._pending_option: str | None = None

    def _profiles_by_slot(self) -> dict[int, SimProfile]:
        """Return the most recently seen remembered SIM for each slot."""
        result: dict[int, SimProfile] = {}
        for profile in self.coordinator.profiles.values():
            if profile.slot not in {1, 2}:
                continue
            previous = result.get(profile.slot)
            if (
                previous is None
                or (profile.last_seen or "") > (previous.last_seen or "")
                or profile.sim_id == self.coordinator.active_sim_id
            ):
                result[profile.slot] = profile
        return result

    @staticmethod
    def _option(slot: int, profile: SimProfile | None) -> str:
        return f"Slot {slot}: {profile.name}" if profile else f"Slot {slot}"

    @staticmethod
    def _slot(value: object) -> int | None:
        try:
            slot = int(str(value))
        except (TypeError, ValueError):
            return None
        return slot if slot in {1, 2} else None

    @property
    def options(self) -> list[str]:
        profiles = self._profiles_by_slot()
        slots = set(profiles)
        if self.coordinator.data:
            current_slot = self._slot(self.coordinator.data.sim_state.get("slot"))
            if current_slot is not None:
                slots.add(current_slot)
            primary_slot = self._slot(
                self.coordinator.data.sim_config.get("primary-slot-id")
            )
            if primary_slot is not None:
                slots.add(primary_slot)
        return [self._option(slot, profiles.get(slot)) for slot in sorted(slots)]

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and bool(self.coordinator.data.sim_config)
            and len(self.options) >= 2
        )

    @property
    def current_option(self) -> str | None:
        if self._pending_option is not None:
            return self._pending_option
        if not self.coordinator.data:
            return None
        slot = self._slot(
            self.coordinator.data.sim_config.get("primary-slot-id")
        )
        if slot is None:
            return None
        return self._option(slot, self._profiles_by_slot().get(slot))

    async def async_select_option(self, option: str) -> None:
        for slot_option in self.options:
            if option != slot_option:
                continue
            slot = int(slot_option.split(":", 1)[0].removeprefix("Slot "))
            self._pending_option = option
            self.async_write_ha_state()
            try:
                await self.coordinator.async_select_sim_slot(slot)
            finally:
                self._pending_option = None
                self.async_write_ha_state()
            return
        raise HomeAssistantError(f"Unknown SIM selection: {option}")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[U5GRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the active-SIM selector."""
    async_add_entities([U5GPrimarySimSelect(entry.runtime_data.coordinator)])
