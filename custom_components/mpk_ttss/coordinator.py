"""Data update coordinator for MPK Kraków (TTSS)."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Departure, MpkTtssApi, MpkTtssError
from .gtfs import GtfsError, fetch_timetable
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
        self._schedule: list[Departure] = []
        self._schedule_day: date | None = None
        self._loading_schedule = False
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
        realtime = sorted(
            (
                replace(
                    departure,
                    in_minutes=int((departure.at - now).total_seconds() // 60),
                )
                for departure in self._seen.values()
            ),
            key=lambda departure: departure.at,
        )

        self._schedule_requested(now)
        return self._merge_with_schedule(realtime, now)

    def _merge_with_schedule(
        self, realtime: list[Departure], now: datetime
    ) -> list[Departure]:
        """Extend the realtime window with timetabled departures beyond it.

        Realtime always wins where it has anything to say. Only departures later
        than the furthest realtime one are taken from the timetable, which keeps
        the same run from appearing twice when its realtime time has drifted from
        the scheduled one.
        """
        if not self._schedule:
            return realtime

        horizon = realtime[-1].at if realtime else now
        extra = [
            replace(
                departure,
                in_minutes=int((departure.at - now).total_seconds() // 60),
            )
            for departure in self._schedule
            if departure.at > horizon
        ]
        return realtime + extra

    def _schedule_requested(self, now: datetime) -> None:
        """Load today's timetable in the background, once per service day.

        Downloading ~20 MB and scanning it takes seconds to a minute on slower
        hardware, so it must never sit in the update path - a stop shows its
        realtime window immediately and gains the rest of the day once this
        finishes.
        """
        today = now.date()
        if self._schedule_day == today or self._loading_schedule:
            return
        self._loading_schedule = True
        self.hass.async_create_background_task(
            self._async_load_schedule(today), f"{DOMAIN}_schedule_{self.stop_id}"
        )

    async def _async_load_schedule(self, service_day: date) -> None:
        """Fetch and extract this stop's timetable for one service day."""
        from . import async_get_feed

        try:
            payload = await async_get_feed(self.hass, self.vehicle_type)
            scheduled = await self.hass.async_add_executor_job(
                fetch_timetable, payload, self.stop_id, service_day, self.lines
            )
        except GtfsError as err:
            _LOGGER.warning(
                "Timetable unavailable for stop %s, realtime window only: %s",
                self.stop_id,
                err,
            )
            return
        finally:
            self._loading_schedule = False

        self._schedule = [
            Departure(
                time=item.time,
                line=item.line,
                direction=item.direction,
                at=item.at,
                in_minutes=0,
                realtime=False,
            )
            for item in scheduled
        ]
        self._schedule_day = service_day
        _LOGGER.debug(
            "Loaded %d timetabled departures for stop %s",
            len(self._schedule),
            self.stop_id,
        )
        await self.async_request_refresh()
