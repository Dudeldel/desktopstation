"""Thin async wrapper around the keyless OpenMeteo forecast endpoint."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class WeatherSnapshot:
    temp_c: float
    weather_code: int  # WMO interpretation code (0 clear, 1-3 cloudy, 51-67 rain, ...)


class OpenMeteoClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=10.0)
        self._owns_http = http_client is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def current(self, latitude: float, longitude: float) -> WeatherSnapshot:
        params = {
            "latitude": str(latitude),
            "longitude": str(longitude),
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
        resp = await self._http.get(_OPENMETEO_URL, params=params)
        resp.raise_for_status()
        body = resp.json()
        current = body["current"]
        return WeatherSnapshot(
            temp_c=float(current["temperature_2m"]),
            weather_code=int(current["weather_code"]),
        )
