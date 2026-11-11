"""Restore buttons for U5G Control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import U5GRuntimeData
from .coordinator import U5GCoordinator
from .entity import U5GSimEntity


class U5GRestoreButton(U5GSimEntity, ButtonEntity):
    """Restore a captured radio preference."""

    def __init__(self, coordinator: U5GCoordinator, sim_id: str, target: str) -> None:
        super().__init__(coordinator, sim_id, f"button:restore_{target}")
        self.target = target
        self._attr_name = f"Restore {target} configuration"
        self._attr_icon = "mdi:restore"

    async def async_press(self) -> None:
        if self.target == "default":
            await self.coordinator.async_restore_default(self.sim_id)
        else:
            await self.coordinator.async_restore_previous(self.sim_id)


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
        async_add_entities(
            [
                U5GRestoreButton(coordinator, sim_id, target)
                for sim_id in new
                for target in ("default", "previous")
            ]
        )

    add_new_sims()
    entry.async_on_unload(coordinator.async_add_listener(add_new_sims))

