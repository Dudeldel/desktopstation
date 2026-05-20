import httpx
import pytest
import respx

from deskstation.clients.openmeteo import OpenMeteoClient, WeatherSnapshot

OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"


@respx.mock
async def test_openmeteo_parses_current_weather() -> None:
    respx.get(OPENMETEO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-05-20T10:00",
                    "temperature_2m": 18.4,
                    "weather_code": 1,
                }
            },
        )
    )
    client = OpenMeteoClient()
    try:
        snap = await client.current(latitude=52.23, longitude=21.01)
    finally:
        await client.aclose()
    assert isinstance(snap, WeatherSnapshot)
    assert snap.temp_c == 18.4
    assert snap.weather_code == 1


@respx.mock
async def test_openmeteo_500_raises() -> None:
    respx.get(OPENMETEO_URL).mock(return_value=httpx.Response(500))
    client = OpenMeteoClient()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.current(latitude=52.23, longitude=21.01)
    finally:
        await client.aclose()
