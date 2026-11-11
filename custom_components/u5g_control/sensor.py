"""Sensors for U5G Control."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import U5GRuntimeData
from .carrier import carrier_width_mhz
from .coordinator import U5GCoordinator
from .entity import U5GHubEntity, U5GSimEntity
from .radio_status import current_mode


def _status(coordinator: U5GCoordinator) -> dict[str, Any]:
    return coordinator.data.radio_status if coordinator.data else {}


def _component_carrier(
    status: dict[str, Any], technology: str, index: int
) -> dict[str, Any] | None:
    """Return one carrier-aggregation record when supplied by the modem."""
    carriers = status.get("ca-nr" if technology == "nr" else "ca-lte")
    if not isinstance(carriers, list) or index >= len(carriers):
        return None
    carrier = carriers[index]
    return carrier if isinstance(carrier, dict) else None


class U5GActiveSimSensor(U5GHubEntity, SensorEntity):
    """Show the active SIM child."""

    _attr_name = "Active SIM"
    _attr_icon = "mdi:sim"

    def __init__(self, coordinator: U5GCoordinator) -> None:
        super().__init__(coordinator, "active_sim")

    @property
    def native_value(self) -> str | None:
        sim_id = self.coordinator.active_sim_id
        return self.coordinator.profiles[sim_id].name if sim_id else None


class U5GConnectionSensor(U5GHubEntity, SensorEntity):
    """Show the current modem connection mode."""

    _attr_name = "Current mode"
    _attr_icon = "mdi:signal-5g"

    def __init__(self, coordinator: U5GCoordinator) -> None:
        super().__init__(coordinator, "connection_mode")

    @property
    def native_value(self) -> str:
        return current_mode(_status(self.coordinator))


class U5GCarrierSensor(U5GSimEntity, SensorEntity):
    """Expose one LTE or NR component carrier and all reported statistics."""

    _attr_icon = "mdi:access-point-network"

    def __init__(
        self,
        coordinator: U5GCoordinator,
        sim_id: str,
        technology: str,
        index: int,
    ) -> None:
        super().__init__(
            coordinator,
            sim_id,
            f"sensor:{technology}_carrier_{index + 1}",
        )
        self.technology = technology
        self.index = index
        label = "5G" if technology == "nr" else "LTE"
        self._attr_name = f"{label} carrier {index + 1}"

    @property
    def native_value(self) -> str:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None or carrier.get("band") is None:
            return "Not connected"
        prefix = "n" if self.technology == "nr" else "b"
        return f"{prefix}{carrier['band']}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None:
            return {
                "technology": "5G NR" if self.technology == "nr" else "LTE",
                "carrier_number": self.index + 1,
                "connected": False,
            }
        return {
            "technology": "5G NR" if self.technology == "nr" else "LTE",
            "carrier_number": self.index + 1,
            "connected": True,
            **carrier,
        }


class U5GCarrierWidthSensor(U5GSimEntity, SensorEntity):
    """Expose one component carrier's channel width."""

    _attr_icon = "mdi:arrow-expand-horizontal"

    def __init__(
        self,
        coordinator: U5GCoordinator,
        sim_id: str,
        technology: str,
        index: int,
    ) -> None:
        super().__init__(
            coordinator,
            sim_id,
            f"sensor:{technology}_carrier_{index + 1}_width",
        )
        self.technology = technology
        self.index = index
        label = "5G" if technology == "nr" else "LTE"
        self._attr_name = f"{label} carrier {index + 1} width"

    @property
    def native_value(self) -> int | float | str:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None:
            return "Not connected"
        value = carrier_width_mhz(carrier)
        return value if value is not None else "Unknown"

    @property
    def native_unit_of_measurement(self) -> str | None:
        value = carrier_width_mhz(
            _component_carrier(
                _status(self.coordinator), self.technology, self.index
            )
        )
        return "MHz" if value is not None else None


class U5GSimSensor(U5GSimEntity, SensorEntity):
    """One live measurement associated with the active SIM."""

    def __init__(
        self,
        coordinator: U5GCoordinator,
        sim_id: str,
        key: str,
        name: str,
        icon: str,
        value_fn: Callable[[dict[str, Any]], Any],
        unit: str | None = None,
    ) -> None:
        super().__init__(coordinator, sim_id, f"sensor:{key}")
        self._attr_name = name
        self._attr_icon = icon
        self._value_fn = value_fn
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> Any:
        return self._value_fn(_status(self.coordinator))


def _sim_sensors(coordinator: U5GCoordinator, sim_id: str) -> list[SensorEntity]:
    sensors: list[SensorEntity] = [
        U5GSimSensor(coordinator, sim_id, "carrier", "Carrier", "mdi:access-point-network", lambda s: s.get("registered-spn")),
        U5GSimSensor(coordinator, sim_id, "primary_band", "Primary band", "mdi:sine-wave", lambda s: s.get("band-class")),
        U5GSimSensor(coordinator, sim_id, "rsrp", "RSRP", "mdi:signal", lambda s: s.get("rsrp-nr", s.get("rsrp")), SIGNAL_STRENGTH_DECIBELS_MILLIWATT),
        U5GSimSensor(coordinator, sim_id, "rsrq", "RSRQ", "mdi:signal", lambda s: s.get("rsrq-nr", s.get("rsrq")), "dB"),
        U5GSimSensor(coordinator, sim_id, "sinr", "SINR", "mdi:signal", lambda s: s.get("snr-nr", s.get("snr")), "dB"),
    ]
    sensors.extend(
        entity
        for technology in ("lte", "nr")
        for index in range(3)
        for entity in (
            U5GCarrierSensor(coordinator, sim_id, technology, index),
            U5GCarrierWidthSensor(coordinator, sim_id, technology, index),
        )
    )
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[U5GRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([U5GActiveSimSensor(coordinator), U5GConnectionSensor(coordinator)])
    known: set[str] = set()

    @callback
    def add_new_sims() -> None:
        new = [sim_id for sim_id in coordinator.profiles if sim_id not in known]
        if not new:
            return
        for sim_id in new:
            known.add(sim_id)
        async_add_entities([entity for sim_id in new for entity in _sim_sensors(coordinator, sim_id)])

    add_new_sims()
    entry.async_on_unload(coordinator.async_add_listener(add_new_sims))

