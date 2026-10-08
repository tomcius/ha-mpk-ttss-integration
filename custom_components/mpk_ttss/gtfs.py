"""Static timetable from the official MPK GTFS feed.

The realtime API only exposes a 30-minute window, so a line running every two
hours is invisible most of the day. The GTFS feed carries the full timetable and
is published by MPK itself, which makes it the right second source: its stop ids
are the TTSS ids without the leading zero (TTSS "017269" is GTFS 17269).

The feed is large - stop_times.txt alone unpacks to ~137 MB - so it is never
held in memory or on disk in full. The archive is streamed row by row and only
the rows of the requested stop survive, which leaves a few dozen kilobytes.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import aiohttp

from homeassistant.util import dt as dt_util

from .const import GTFS_URLS, TYPE_BUS

_LOGGER = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=300)


class GtfsError(Exception):
    """Raised when the GTFS feed cannot be fetched or parsed."""


@dataclass(frozen=True)
class ScheduledDeparture:
    """One timetabled departure, before any realtime correction."""

    time: str
    line: str
    direction: str
    at: datetime


def _normalise_stop_id(stop_id: str) -> str:
    """TTSS pads stop ids with a leading zero; GTFS does not."""
    return stop_id.lstrip("0") or "0"


def _parse_gtfs_time(value: str, service_day: date) -> datetime | None:
    """Parse "HH:MM:SS", where GTFS allows hours past 24 for after-midnight runs."""
    parts = value.split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None

    # 24:07 means 00:07 on the following calendar day, still belonging to this
    # service day. Treating it as an invalid hour would silently drop the last
    # runs of the night.
    extra_days, hour = divmod(hour, 24)
    naive = datetime.combine(service_day, datetime.min.time()).replace(
        hour=hour, minute=minute
    ) + timedelta(days=extra_days)
    return naive.replace(tzinfo=dt_util.now().tzinfo)


def _read_csv(archive: zipfile.ZipFile, name: str):
    """Yield rows of a member file without unpacking it to disk."""
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def fetch_timetable(
    payload: bytes,
    stop_id: str,
    service_day: date,
    lines: list[str] | None = None,
) -> list[ScheduledDeparture]:
    """Extract one stop's timetable for one day from a GTFS archive.

    Runs blocking work on purpose - the caller is expected to hand it to an
    executor.
    """
    wanted_stop = _normalise_stop_id(stop_id)
    wanted_lines = {line.strip() for line in lines} if lines else None
    day_key = service_day.strftime("%Y%m%d")

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            # Krakow leaves calendar.txt all zeros and expresses every service
            # day as an exception, so the dates file is the only source of truth.
            active = {
                row["service_id"]
                for row in _read_csv(archive, "calendar_dates.txt")
                if row["date"] == day_key and row["exception_type"] == "1"
            }
            if not active:
                raise GtfsError(f"GTFS feed covers no service for {day_key}")

            routes = {
                row["route_id"]: (row.get("route_short_name") or row["route_id"])
                for row in _read_csv(archive, "routes.txt")
            }
            trips = {
                row["trip_id"]: routes.get(row["route_id"], row["route_id"])
                for row in _read_csv(archive, "trips.txt")
                if row["service_id"] in active
            }

            seen: set[tuple[str, str, str]] = set()
            departures: list[ScheduledDeparture] = []
            for row in _read_csv(archive, "stop_times.txt"):
                if row["stop_id"] != wanted_stop:
                    continue
                line = trips.get(row["trip_id"])
                if line is None:
                    continue
                if wanted_lines is not None and line not in wanted_lines:
                    continue

                raw_time = row["departure_time"]
                at = _parse_gtfs_time(raw_time, service_day)
                if at is None:
                    continue

                direction = (row.get("stop_headsign") or "").strip().strip('"')
                key = (raw_time, line, direction)
                if key in seen:
                    continue
                seen.add(key)
                departures.append(
                    ScheduledDeparture(at.strftime("%H:%M"), line, direction, at)
                )
    except KeyError as err:
        raise GtfsError(f"Unexpected GTFS layout: missing {err}") from err
    except zipfile.BadZipFile as err:
        raise GtfsError("GTFS download is not a valid archive") from err

    departures.sort(key=lambda departure: departure.at)
    return departures


async def async_download_feed(
    session: aiohttp.ClientSession, vehicle_type: str
) -> bytes:
    """Download the GTFS archive for buses or trams."""
    url = GTFS_URLS.get(vehicle_type, GTFS_URLS[TYPE_BUS])
    try:
        async with session.get(url, timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            return await response.read()
    except aiohttp.ClientError as err:
        raise GtfsError(f"Cannot download GTFS feed: {err}") from err
