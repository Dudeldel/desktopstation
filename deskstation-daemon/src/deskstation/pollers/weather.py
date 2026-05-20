"""OpenMeteo weather poller — patches ``top_bar.weather``.

WMO code → icon mapping (broad buckets):

  0           → ☀
  1, 2, 3     → ☁
  45, 48      → 🌫
  51-67       → 🌧
  71-86       → 🌨
  95-99       → ⛈

Temperature rounds to integer °C.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import structlog

from deskstation.clients.openmeteo import OpenMeteoClient, WeatherSnapshot

if TYPE_CHECKING:
    from deskstation.ui_state import UIState

log = structlog.get_logger(__name__)


def format_weather(snap: WeatherSnapshot) -> str:
    code = snap.weather_code
    if code == 0:
        icon = "☀"
    elif code in (1, 2, 3):
        icon = "☁"
    elif code in (45, 48):
        icon = "🌫"
    elif 51 <= code <= 67:
        icon = "🌧"
    elif 71 <= code <= 86:
        icon = "🌨"
    elif 95 <= code <= 99:
        icon = "⛈"
    else:
        icon = "☁"
    return f"{round(snap.temp_c)}°C {icon}"


class WeatherPoller:
    def __init__(
        self,
        ui_state: UIState,
        client: OpenMeteoClient,
        latitude: float,
        longitude: float,
        interval_sec: float = 15 * 60,
    ) -> None:
        self._ui = ui_state
        self._client = client
        self._lat = latitude
        self._lon = longitude
        self.interval_sec = interval_sec

    async def tick(self) -> None:
        try:
            snap = await self._client.current(self._lat, self._lon)
        except httpx.HTTPError as exc:
            log.warning("weather_tick_failed", error=str(exc))
            return
        self._ui.set_weather(format_weather(snap))

    async def run_forever(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self.interval_sec)
