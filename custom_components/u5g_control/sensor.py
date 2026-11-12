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
from .carrier import carrier_downlink_width_mhz, carrier_uplink_width_mhz
from .coordinator import U5GCoordinator
from .entity import U5GHubEntity, U5GSimEntity
from .radio_status import current_mode, lte_measurement, rounded_measurement


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


class U5GModeSensor(U5GSimEntity, SensorEntity):
    """Show the active radio mode for one SIM."""

    _attr_name = "Mode"
    _attr_icon = "mdi:signal-5g"

    def __init__(self, coordinator: U5GCoordinator, sim_id: str) -> None:
        super().__init__(coordinator, sim_id, "sensor:mode")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str:
        if not self.coordinator.is_active(self.sim_id):
            return "Not connected"
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
    """Expose one directional component-carrier channel width."""

    _attr_icon = "mdi:arrow-expand-horizontal"

    def __init__(
        self,
        coordinator: U5GCoordinator,
        sim_id: str,
        technology: str,
        index: int,
        direction: str,
    ) -> None:
        suffix = "width" if direction == "download" else "upload_width"
        super().__init__(
            coordinator,
            sim_id,
            f"sensor:{technology}_carrier_{index + 1}_{suffix}",
        )
        self.technology = technology
        self.index = index
        self.direction = direction
        label = "5G" if technology == "nr" else "LTE"
        self._attr_name = f"{label} carrier {index + 1} {direction} bandwidth"
        if self._attr_suggested_object_id:
            self._attr_suggested_object_id = (
                self._attr_suggested_object_id.removesuffix("_width")
                + "_bandwidth"
            )

    def _width(self, carrier: dict[str, Any] | None) -> int | float | None:
        if self.direction == "download":
            return carrier_downlink_width_mhz(carrier)
        return carrier_uplink_width_mhz(carrier)

    @property
    def native_value(self) -> int | float | str:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None:
            return "Not connected"
        value = self._width(carrier)
        return value if value is not None else "Unknown"

    @property
    def native_unit_of_measurement(self) -> str | None:
        value = self._width(
            _component_carrier(
                _status(self.coordinator), self.technology, self.index
            )
        )
        return "MHz" if value is not None else None


class U5GCarrierSignalSensor(U5GSimEntity, SensorEntity):
    """Expose the strongest reported receive path for one carrier."""

    _attr_icon = "mdi:signal"

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
            f"sensor:{technology}_carrier_{index + 1}_rssi",
        )
        self.technology = technology
        self.index = index
        label = "5G" if technology == "nr" else "LTE"
        self._attr_name = f"{label} carrier {index + 1} RSSI"

    @property
    def native_value(self) -> int | float | str:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None:
            return "Not connected"
        value = carrier.get("rssi-dbm")
        return value if isinstance(value, (int, float)) else "Not reported"

    @property
    def native_unit_of_measurement(self) -> str | None:
        value = self.native_value
        return SIGNAL_STRENGTH_DECIBELS_MILLIWATT if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        carrier = _component_carrier(
            _status(self.coordinator), self.technology, self.index
        )
        if carrier is None:
            return None
        return {
            key: value
            for key, value in carrier.items()
            if key.startswith("rssi-rx") or key == "rssi-average-dbm"
        } or None


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
        suggested_key: str | None = None,
        missing_value: str | None = None,
    ) -> None:
        super().__init__(coordinator, sim_id, f"sensor:{key}")
        if suggested_key and self._attr_suggested_object_id:
            self._attr_suggested_object_id = (
                self._attr_suggested_object_id.removesuffix(f"_{key}")
                + f"_{suggested_key}"
            )
        self._attr_name = name
        self._attr_icon = icon
        self._value_fn = value_fn
        self._unit = unit
        self._missing_value = missing_value

    @property
    def native_value(self) -> Any:
        value = self._value_fn(_status(self.coordinator))
        if value is None and self._missing_value is not None:
            return self._missing_value
        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._unit if isinstance(self.native_value, (int, float)) else None


def _sim_sensors(coordinator: U5GCoordinator, sim_id: str) -> list[SensorEntity]:
    sensors: list[SensorEntity] = [
        U5GModeSensor(coordinator, sim_id),
        U5GSimSensor(coordinator, sim_id, "carrier", "Carrier", "mdi:access-point-network", lambda s: s.get("registered-spn")),
        U5GSimSensor(coordinator, sim_id, "primary_band", "Primary band", "mdi:sine-wave", lambda s: s.get("band-class")),
        U5GSimSensor(coordinator, sim_id, "rsrp", "5G RSRP", "mdi:signal", lambda s: s.get("rsrp-nr"), SIGNAL_STRENGTH_DECIBELS_MILLIWATT, "5g_rsrp", "Not connected"),
        U5GSimSensor(coordinator, sim_id, "rsrq", "5G RSRQ", "mdi:signal", lambda s: s.get("rsrq-nr"), "dB", "5g_rsrq", "Not connected"),
        U5GSimSensor(coordinator, sim_id, "sinr", "5G SINR", "mdi:signal", lambda s: rounded_measurement(s.get("snr-nr")), "dB", "5g_sinr", "Not connected"),
        U5GSimSensor(coordinator, sim_id, "lte_rsrp", "LTE RSRP", "mdi:signal", lambda s: lte_measurement(s, "rsrp"), SIGNAL_STRENGTH_DECIBELS_MILLIWATT, missing_value="Not connected"),
        U5GSimSensor(coordinator, sim_id, "lte_rsrq", "LTE RSRQ", "mdi:signal", lambda s: lte_measurement(s, "rsrq"), "dB", missing_value="Not connected"),
        U5GSimSensor(coordinator, sim_id, "lte_sinr", "LTE SINR", "mdi:signal", lambda s: rounded_measurement(lte_measurement(s, "snr")), "dB", missing_value="Not connected"),
    ]
    sensors.extend(
        entity
        for technology in ("lte", "nr")
        for index in range(3)
        for entity in (
            U5GCarrierSensor(coordinator, sim_id, technology, index),
            U5GCarrierWidthSensor(coordinator, sim_id, technology, index, "download"),
            U5GCarrierWidthSensor(coordinator, sim_id, technology, index, "upload"),
            U5GCarrierSignalSensor(coordinator, sim_id, technology, index),
        )
    )
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[U5GRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities([U5GActiveSimSensor(coordinator)])
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

