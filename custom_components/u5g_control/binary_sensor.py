"""Binary sensors for U5G Control."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import U5GRuntimeData
from .coordinator import U5GCoordinator
from .entity import U5GHubEntity, U5GSimEntity
from .radio_status import roaming_is_active


class U5GSimActiveBinarySensor(U5GSimEntity, BinarySensorEntity):
    """Remain available for remembered SIMs and show which one is inserted."""

    _attr_name = "Active"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: U5GCoordinator, sim_id: str) -> None:
        super().__init__(coordinator, sim_id, "binary_sensor:active")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_active(self.sim_id)


class U5GRoamingBinarySensor(U5GSimEntity, BinarySensorEntity):
    """Report whether the active SIM is roaming."""

    _attr_name = "Roaming"
    _attr_icon = "mdi:earth"

    def __init__(self, coordinator: U5GCoordinator, sim_id: str) -> None:
        super().__init__(coordinator, sim_id, "binary_sensor:roaming")

    def _roaming(self) -> bool | None:
        status = self.coordinator.data.radio_status if self.coordinator.data else {}
        return roaming_is_active(status)

    @property
    def available(self) -> bool:
        return super().available and self._roaming() is not None

    @property
    def is_on(self) -> bool:
        return self._roaming() is True


class U5GHubRoamingBinarySensor(U5GHubEntity, BinarySensorEntity):
    """Mirror roaming state for whichever SIM is currently active."""

    _attr_name = "Roaming"
    _attr_icon = "mdi:earth"

    def __init__(self, coordinator: U5GCoordinator) -> None:
        super().__init__(coordinator, "binary_sensor:roaming")

    def _roaming(self) -> bool | None:
        if not self.coordinator.active_sim_id:
            return None
        status = self.coordinator.data.radio_status if self.coordinator.data else {}
        return roaming_is_active(status)

    @property
    def available(self) -> bool:
        return super().available and self._roaming() is not None

    @property
    def is_on(self) -> bool:
        return self._roaming() is True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[U5GRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([U5GHubRoamingBinarySensor(coordinator)])
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
                entity
                for sim_id in new
                for entity in (
                    U5GSimActiveBinarySensor(coordinator, sim_id),
                    U5GRoamingBinarySensor(coordinator, sim_id),
                )
            ]
        )

    add_new_sims()
    entry.async_on_unload(coordinator.async_add_listener(add_new_sims))

