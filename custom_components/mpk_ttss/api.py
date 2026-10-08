"""Client for the api.ttss.pl departure API."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from homeassistant.util import dt as dt_util

from .const import API_BASE, MIDNIGHT_ROLLOVER_GRACE_MINUTES

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
STOPS_CACHE_TTL = timedelta(hours=6)


class MpkTtssError(Exception):
    """Raised when the TTSS API cannot be reached or returns garbage."""


@dataclass(frozen=True)
class Stop:
    """A single TTSS stop point (one physical pole, one direction)."""

    id: str
    name: str
    lat: float | None
    lon: float | None
    parent: str | None


@dataclass(frozen=True)
class Departure:
    """One upcoming departure."""

    time: str
    line: str
    direction: str
    at: datetime
    in_minutes: int


class MpkTtssApi:
    """Thin async wrapper over api.ttss.pl."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._stops_cache: dict[str, tuple[datetime, list[Stop]]] = {}

    async def _get_json(self, path: str, params: dict[str, str]):
        try:
            async with self._session.get(
                f"{API_BASE}{path}", params=params, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise MpkTtssError(f"Timeout calling {path}") from err
        except aiohttp.ClientError as err:
            raise MpkTtssError(f"Error calling {path}: {err}") from err
        except ValueError as err:
            raise MpkTtssError(f"Invalid JSON from {path}: {err}") from err

    async def async_get_stops(self, vehicle_type: str) -> list[Stop]:
        """Return every stop of a given type, cached because the list is static."""
        cached = self._stops_cache.get(vehicle_type)
        if cached and dt_util.utcnow() - cached[0] < STOPS_CACHE_TTL:
            return cached[1]

        payload = await self._get_json("/stops/", {"type": vehicle_type})
        if not isinstance(payload, list):
            raise MpkTtssError("Unexpected payload for stop list")

        stops = [
            Stop(
                id=str(item["id"]),
                name=str(item.get("name", "")),
                lat=item.get("lat"),
                lon=item.get("lon"),
                parent=item.get("parent"),
            )
            for item in payload
            if item.get("id")
        ]
        self._stops_cache[vehicle_type] = (dt_util.utcnow(), stops)
        return stops

    async def async_find_stop(self, vehicle_type: str, stop_id: str) -> Stop | None:
        """Return a single stop by exact id, or None when it does not exist."""
        for stop in await self.async_get_stops(vehicle_type):
            if stop.id == stop_id:
                return stop
        return None

    async def async_search_stops(
        self, vehicle_type: str, query: str, limit: int = 25
    ) -> list[Stop]:
        """Return stops whose name contains the query, case-insensitively."""
        needle = query.strip().casefold()
        if not needle:
            return []

        matches = [
            stop
            for stop in await self.async_get_stops(vehicle_type)
            # A parent entry is the stop group; we only offer individual poles,
            # because a group mixes both travel directions together.
            if stop.parent is not None and needle in stop.name.casefold()
        ]
        matches.sort(key=lambda stop: (stop.name.casefold(), stop.id))
        return matches[:limit]

    async def async_get_departures(
        self,
        vehicle_type: str,
        stop_id: str,
        lines: list[str] | None = None,
        include_departed: bool = False,
    ) -> list[Departure]:
        """Return deduplicated departures, soonest first.

        With include_departed the already-left ones are kept too, which is how
        the full set of lines and directions a stop serves is discovered: a
        stop point can serve several directions, and asking only about future
        departures gives whatever happens to be due in the next few minutes.
        """
        payload = await self._get_json(
            "/schedule/", {"type": vehicle_type, "id": stop_id}
        )
        if not isinstance(payload, list):
            raise MpkTtssError("Unexpected payload for schedule")

        now = dt_util.now()
        wanted = {line.strip() for line in lines} if lines else None

        seen: set[tuple[str, str, str]] = set()
        departures: list[Departure] = []

        for item in payload:
            raw_time = str(item.get("time", "")).strip()
            line = str(item.get("line", "")).strip()
            direction = str(item.get("direction", "")).strip()

            key = (raw_time, line, direction)
            # The API returns every record twice; keep the first occurrence.
            if key in seen:
                continue
            seen.add(key)

            if wanted is not None and line not in wanted:
                continue

            at = _parse_departure_time(raw_time, now)
            if at is None:
                continue

            in_minutes = int((at - now).total_seconds() // 60)
            if in_minutes < 0 and not include_departed:
                continue

            departures.append(
                Departure(
                    time=raw_time,
                    line=line,
                    direction=direction,
                    at=at,
                    in_minutes=in_minutes,
                )
            )

        departures.sort(key=lambda departure: departure.at)
        return departures


def _parse_departure_time(raw_time: str, now: datetime) -> datetime | None:
    """Turn an "HH:MM" wall-clock string into an absolute local datetime."""
    try:
        hour, minute = (int(part) for part in raw_time.split(":", 1))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        _LOGGER.debug("Unparseable departure time %r", raw_time)
        return None

    # The API sends a bare wall clock, so a departure shortly after midnight
    # looks like it happened ~24 h ago. Roll it forward instead of dropping it.
    if (candidate - now) < -timedelta(minutes=MIDNIGHT_ROLLOVER_GRACE_MINUTES):
        candidate += timedelta(days=1)
    return candidate
