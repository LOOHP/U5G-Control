"""U5G Control integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import U5GClient
from .const import (
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
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


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)

