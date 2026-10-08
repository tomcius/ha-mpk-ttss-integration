"""Sensor platform for MPK Kraków (TTSS)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MpkTtssConfigEntry
from .const import (
    ATTR_BY_LINE,
    ATTR_DEPARTURES,
    ATTR_DIRECTIONS,
    ATTR_NEXT_TWO,
    ATTR_STOP_ID,
    ATTR_STOP_NAME,
    DOMAIN,
    TYPE_TRAM,
)
from .coordinator import MpkTtssCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MpkTtssConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the departure sensor for this stop point."""
    async_add_entities([MpkTtssDepartureSensor(entry.runtime_data, entry)])


class MpkTtssDepartureSensor(CoordinatorEntity[MpkTtssCoordinator], SensorEntity):
    """Minutes until the next departure, with the full list in attributes."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_unit_of_measurement = "min"

    def __init__(
        self, coordinator: MpkTtssCoordinator, entry: MpkTtssConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.vehicle_type}_{coordinator.stop_id}"
        self._attr_icon = (
            "mdi:tram" if coordinator.vehicle_type == TYPE_TRAM else "mdi:bus"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=entry.title,
            manufacturer="MPK Kraków",
            model=f"Przystanek {coordinator.stop_id}",
            configuration_url=(
                f"https://beta.ttss.pl/map.html#!p{coordinator.vehicle_type}"
                f"{coordinator.stop_id}"
            ),
        )

    @property
    def native_value(self) -> int | None:
        """Minutes until the soonest departure, or None when nothing is due."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data[0].in_minutes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        departures = self.coordinator.data or []
        return {
            ATTR_STOP_ID: self.coordinator.stop_id,
            ATTR_STOP_NAME: self.coordinator.stop_name,
            ATTR_DIRECTIONS: sorted(
                {departure.direction for departure in departures if departure.direction}
            ),
            ATTR_DEPARTURES: [
                {
                    "time": departure.time,
                    "line": departure.line,
                    "direction": departure.direction,
                    "in_minutes": departure.in_minutes,
                    "realtime": departure.realtime,
                }
                for departure in departures
            ],
            ATTR_NEXT_TWO: _format_next_two(departures),
            ATTR_BY_LINE: _group_by_line(departures),
        }


def _group_by_line(departures: list[Any]) -> dict[str, list[dict[str, Any]]]:
    """The next two departures of each line, keyed by line number."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for departure in departures:
        entries = grouped.setdefault(departure.line, [])
        if len(entries) < 2:
            entries.append(
                {
                    "time": departure.time,
                    "in_minutes": departure.in_minutes,
                    "direction": departure.direction,
                    "realtime": departure.realtime,
                }
            )
    return grouped


def _format_next_two(departures: list[Any]) -> str:
    """Render the first two departures as "1. 5 min, 2. 29 min"."""
    if not departures:
        return "Brak odjazdów"
    return ", ".join(
        f"{index}. {departure.in_minutes} min"
        for index, departure in enumerate(departures[:2], start=1)
    )
