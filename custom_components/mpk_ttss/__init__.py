"""The MPK Kraków (TTSS) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

import asyncio
from datetime import datetime, timedelta

from .api import MpkTtssApi
from .coordinator import MpkTtssCoordinator
from .const import DOMAIN
from .gtfs import async_download_feed

PLATFORMS: list[Platform] = [Platform.SENSOR]

# The archive is ~20 MB. Hold it only long enough for every configured stop to
# extract its own rows from the same download, then let it go.
FEED_CACHE_TTL = timedelta(minutes=10)

MpkTtssConfigEntry = ConfigEntry[MpkTtssCoordinator]


async def async_get_feed(hass: HomeAssistant, vehicle_type: str) -> bytes:
    """Download the GTFS archive, sharing one download between stops."""
    store = hass.data.setdefault(DOMAIN, {})
    locks = store.setdefault("feed_locks", {})
    lock = locks.setdefault(vehicle_type, asyncio.Lock())

    async with lock:
        cached = store.get(f"feed_{vehicle_type}")
        if cached and datetime.now() - cached[0] < FEED_CACHE_TTL:
            return cached[1]

        payload = await async_download_feed(
            async_get_clientsession(hass), vehicle_type
        )
        store[f"feed_{vehicle_type}"] = (datetime.now(), payload)

        async def _drop() -> None:
            await asyncio.sleep(FEED_CACHE_TTL.total_seconds())
            store.pop(f"feed_{vehicle_type}", None)

        hass.async_create_background_task(_drop(), f"{DOMAIN}_drop_feed")
        return payload


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
