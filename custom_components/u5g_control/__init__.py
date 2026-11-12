"""U5G Control integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api import U5GClient
from .const import (
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import U5GCoordinator


@dataclass(slots=True)
class U5GRuntimeData:
    """Runtime objects for one modem config entry."""

    client: U5GClient
    coordinator: U5GCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one physical U5G modem hub."""
    client = U5GClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        host_key=entry.data[CONF_HOST_KEY],
    )
    modem_info = dict(entry.data.get("modem_info", {}))
    modem_id = str(entry.unique_id or modem_info.get("mac") or entry.entry_id)
    coordinator = U5GCoordinator(hass, entry, client, modem_id, modem_info)
    try:
        await coordinator.async_load()
        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = U5GRuntimeData(client, coordinator)
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform(platform) for platform in PLATFORMS]
        )
    except BaseException:
        await client.async_close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one modem hub."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform(platform) for platform in PLATFORMS]
    )
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry[U5GRuntimeData],
    device_entry: dr.AnyDeviceEntry,
) -> bool:
    """Forget an inactive SIM child when it is deleted from the device UI."""
    runtime = getattr(config_entry, "runtime_data", None)
    if runtime is None:
        return False

    coordinator = runtime.coordinator
    identifier_prefix = f"{coordinator.modem_id}:sim:"
    sim_id = next(
        (
            identifier.removeprefix(identifier_prefix)
            for domain, identifier in device_entry.identifiers
            if domain == DOMAIN and identifier.startswith(identifier_prefix)
        ),
        None,
    )
    if not sim_id or coordinator.is_active(sim_id):
        return False

    await coordinator.async_forget_profiles([sim_id])
    entity_registry = er.async_get(hass)
    for entity in list(
        er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)
    ):
        if f":{sim_id}:" in entity.unique_id:
            entity_registry.async_remove(entity.entity_id)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)

