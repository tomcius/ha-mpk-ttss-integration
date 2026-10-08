"""Data update coordinator for MPK Kraków (TTSS)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Departure, MpkTtssApi, MpkTtssError
from .const import (
    CONF_LINES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_VEHICLE_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class MpkTtssCoordinator(DataUpdateCoordinator[list[Departure]]):
    """Fetches upcoming departures for one stop point."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: MpkTtssApi
    ) -> None:
        self.api = api
        self._seen: dict[tuple[datetime, str, str], Departure] = {}
        self.vehicle_type: str = entry.data[CONF_VEHICLE_TYPE]
        self.stop_id: str = entry.data[CONF_STOP_ID]
        self.stop_name: str = entry.data[CONF_STOP_NAME]

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.stop_name} ({self.stop_id})",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def lines(self) -> list[str] | None:
        """Line filter from options, falling back to the initial config."""
        raw = self.config_entry.options.get(
            CONF_LINES, self.config_entry.data.get(CONF_LINES)
        )
        if not raw:
            return None
        if isinstance(raw, str):
            return [part.strip() for part in raw.split(",") if part.strip()]
        return list(raw)

    async def _async_update_data(self) -> list[Departure]:
        try:
            fresh = await self.api.async_get_departures(
                self.vehicle_type, self.stop_id, self.lines
            )
        except MpkTtssError as err:
            raise UpdateFailed(str(err)) from err

        # The API exposes a narrow sliding window - often a single departure -
        # so a less frequent line drops out of sight between its appearances.
        # Remembering what was already announced keeps every known upcoming
        # departure visible until its time actually passes.
        now = dt_util.now()
        self._seen = {
            key: departure
            for key, departure in self._seen.items()
            if departure.at > now
        }
        for departure in fresh:
            self._seen[(departure.at, departure.line, departure.direction)] = departure

        # in_minutes was computed when each departure was first seen, so it is
        # stale for remembered ones and has to be recomputed against now.
        return sorted(
            (
                replace(
                    departure,
                    in_minutes=int((departure.at - now).total_seconds() // 60),
                )
                for departure in self._seen.values()
            ),
            key=lambda departure: departure.at,
        )
