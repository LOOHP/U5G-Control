"""Shared entities for U5G Control."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import U5GCoordinator
from .entity_ids import suggested_entity_suffix


def hub_device_info(coordinator: U5GCoordinator) -> DeviceInfo:
    """Return the physical modem hub device."""
    info = coordinator.modem_info
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.modem_id)},
        manufacturer="Ubiquiti",
        model=info.get("model", "U5G-class Cellular Modem"),
        name=info.get("hostname", "U5G Cellular Modem"),
        sw_version=info.get("firmware") or None,
    )


def sim_device_info(coordinator: U5GCoordinator, sim_id: str) -> DeviceInfo:
    """Return a remembered SIM child device."""
    profile = coordinator.profile(sim_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{coordinator.modem_id}:sim:{sim_id}")},
        via_device=(DOMAIN, coordinator.modem_id),
        manufacturer=profile.spn or "Mobile network",
        model="eSIM" if profile.esim else "SIM card",
        name=profile.name,
    )


class U5GHubEntity(CoordinatorEntity[U5GCoordinator]):
    """Base entity attached to the physical modem hub."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: U5GCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.modem_id}:hub:{suffix}"
        self._attr_device_info = hub_device_info(coordinator)


class U5GSimEntity(CoordinatorEntity[U5GCoordinator]):
    """Base entity attached to one remembered SIM child."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: U5GCoordinator, sim_id: str, suffix: str) -> None:
        super().__init__(coordinator)
        self.sim_id = sim_id
        self._attr_unique_id = f"{coordinator.modem_id}:{sim_id}:{suffix}"
        self._attr_device_info = sim_device_info(coordinator, sim_id)
        hub_name = (
            coordinator.modem_info.get("hostname")
            or coordinator.modem_info.get("model")
            or coordinator.modem_id
        )
        sim_name = coordinator.profile(sim_id).name
        entity_suffix = suggested_entity_suffix(suffix)
        self._attr_suggested_object_id = slugify(
            f"{hub_name}_{sim_name}_{entity_suffix}"
        )

    @property
    def available(self) -> bool:
        """Live SIM controls and measurements are available only when inserted."""
        return super().available and self.coordinator.is_active(self.sim_id)

