"""The MPK Kraków (TTSS) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MpkTtssApi
from .coordinator import MpkTtssCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

MpkTtssConfigEntry = ConfigEntry[MpkTtssCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MpkTtssConfigEntry) -> bool:
    """Set up one stop point from a config entry."""
    api = MpkTtssApi(async_get_clientsession(hass))
    coordinator = MpkTtssCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MpkTtssConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: MpkTtssConfigEntry) -> None:
    """Reload when the line filter changes so the new filter takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)
