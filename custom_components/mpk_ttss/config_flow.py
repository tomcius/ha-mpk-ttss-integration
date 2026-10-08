"""Config flow for MPK Kraków (TTSS)."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .api import MpkTtssApi, MpkTtssError, Stop
from .const import (
    CONF_LINES,
    CONF_QUERY,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_VEHICLE_TYPE,
    DOMAIN,
    TYPE_BUS,
    TYPE_TRAM,
)

# Looking up a direction costs one request per candidate, so keep the fan-out
# small enough to stay responsive on a slow connection.
MAX_DIRECTION_LOOKUPS = 12
DIRECTION_LOOKUP_TIMEOUT = 12


class MpkTtssConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user from a stop name to a configured stop point."""

    VERSION = 1

    def __init__(self) -> None:
        self._vehicle_type: str = TYPE_BUS
        self._matches: list[Stop] = []
        self._directions: dict[str, str] = {}
        self._stop: Stop | None = None

    @property
    def _api(self) -> MpkTtssApi:
        return MpkTtssApi(async_get_clientsession(self.hass))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick bus or tram — TTSS keeps them in separate datasets."""
        if user_input is not None:
            self._vehicle_type = user_input[CONF_VEHICLE_TYPE]
            return await self.async_step_search()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VEHICLE_TYPE, default=TYPE_BUS): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=TYPE_BUS, label="Autobus"),
                                SelectOptionDict(value=TYPE_TRAM, label="Tramwaj"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Search stops by name."""
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input[CONF_QUERY]
            try:
                self._matches = await self._api.async_search_stops(
                    self._vehicle_type, query
                )
            except MpkTtssError:
                errors["base"] = "cannot_connect"
            else:
                if not self._matches:
                    errors["base"] = "no_results"
                else:
                    self._directions = await self._async_lookup_directions(
                        self._matches
                    )
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema(
                {vol.Required(CONF_QUERY): TextSelector(TextSelectorConfig())}
            ),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one stop point out of the search results."""
        if user_input is not None:
            stop_id = user_input[CONF_STOP_ID]
            self._stop = next(
                (stop for stop in self._matches if stop.id == stop_id), None
            )
            if self._stop is None:
                return await self.async_step_search()

            await self.async_set_unique_id(f"{self._vehicle_type}_{stop_id}")
            self._abort_if_unique_id_configured()
            return await self.async_step_lines()

        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=stop.id, label=self._label_for(stop)
                                )
                                for stop in self._matches
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_lines(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally restrict the sensor to specific lines."""
        assert self._stop is not None

        if user_input is not None:
            lines = _normalise_lines(user_input.get(CONF_LINES))
            return self.async_create_entry(
                title=self._title_for(self._stop),
                data={
                    CONF_VEHICLE_TYPE: self._vehicle_type,
                    CONF_STOP_ID: self._stop.id,
                    CONF_STOP_NAME: self._stop.name,
                },
                options={CONF_LINES: lines},
            )

        available = await self._async_available_lines(self._stop)
        return self.async_show_form(
            step_id="lines",
            data_schema=vol.Schema(
                {vol.Optional(CONF_LINES, default=[]): _lines_selector(available)}
            ),
            description_placeholders={"stop": self._title_for(self._stop)},
        )

    def _label_for(self, stop: Stop) -> str:
        direction = self._directions.get(stop.id)
        if direction:
            return f"{stop.name} → {direction}  [{stop.id}]"
        return f"{stop.name}  [{stop.id}]"

    def _title_for(self, stop: Stop) -> str:
        # Deliberately no direction here. The API only exposes a narrow window
        # of imminent departures, so the directions known at setup time are a
        # snapshot - baking one into the entity name would mislabel the stop
        # for the rest of the day.
        return f"{stop.name} ({stop.id})"

    async def _async_lookup_directions(self, stops: list[Stop]) -> dict[str, str]:
        """Resolve which directions each candidate serves, so poles can be told apart.

        A stop point often serves more than one direction, so every direction in
        the window is collected and sorted - picking the next departure's one
        would make the label depend on the minute the flow happened to run.

        Best-effort: a stop with no departures at all (e.g. late at night) simply
        gets no direction label rather than blocking the flow.
        """
        candidates = stops[:MAX_DIRECTION_LOOKUPS]
        api = self._api

        async def one(stop: Stop) -> tuple[str, str]:
            try:
                departures = await api.async_get_departures(
                    self._vehicle_type, stop.id, include_departed=True
                )
            except MpkTtssError:
                return stop.id, ""
            directions = sorted({d.direction for d in departures if d.direction})
            return stop.id, " / ".join(directions)

        try:
            async with asyncio.timeout(DIRECTION_LOOKUP_TIMEOUT):
                results = await asyncio.gather(
                    *(one(stop) for stop in candidates), return_exceptions=True
                )
        except (asyncio.TimeoutError, TimeoutError):
            return {}

        return {
            stop_id: direction
            for result in results
            if isinstance(result, tuple)
            for stop_id, direction in [result]
            if direction
        }

    async def _async_available_lines(self, stop: Stop) -> list[str]:
        """Lines to prefill the picker with.

        The per-pole window is often a single departure, so the stop group is
        queried as well. That is a superset - a group spans both sides of the
        street - but an over-broad hint beats an empty one, and the picker
        accepts hand-typed values anyway.
        """
        api = self._api
        ids = [stop.id] + ([stop.parent] if stop.parent else [])
        lines: set[str] = set()
        for stop_id in ids:
            try:
                departures = await api.async_get_departures(
                    self._vehicle_type, stop_id, include_departed=True
                )
            except MpkTtssError:
                continue
            lines.update(d.line for d in departures if d.line)
        return sorted(lines)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return MpkTtssOptionsFlow()


class MpkTtssOptionsFlow(OptionsFlow):
    """Let the line filter be changed without re-adding the stop."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_LINES: _normalise_lines(user_input.get(CONF_LINES))}
            )

        entry = self.config_entry
        api = MpkTtssApi(async_get_clientsession(self.hass))
        try:
            departures = await api.async_get_departures(
                entry.data[CONF_VEHICLE_TYPE],
                entry.data[CONF_STOP_ID],
                include_departed=True,
            )
        except MpkTtssError:
            available: list[str] = []
        else:
            available = sorted({d.line for d in departures if d.line})

        current = _normalise_lines(entry.options.get(CONF_LINES))
        # Keep already-selected lines offerable even if none is due right now.
        options = sorted(set(available) | set(current))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_LINES, default=current): _lines_selector(options),
                }
            ),
        )


def _lines_selector(options: list[str]) -> SelectSelector:
    """Multi-select of lines that also accepts hand-typed values."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[SelectOptionDict(value=line, label=line) for line in options],
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _normalise_lines(raw: Any) -> list[str]:
    """Accept a list or a comma-separated string, return a clean list."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [str(part).strip() for part in raw if str(part).strip()]
