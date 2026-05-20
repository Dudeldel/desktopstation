from unittest.mock import AsyncMock

import httpx

from deskstation.clients.openmeteo import WeatherSnapshot
from deskstation.pollers.weather import WeatherPoller, format_weather


def test_format_weather_clear() -> None:
    assert format_weather(WeatherSnapshot(temp_c=18.4, weather_code=0)) == "18°C ☀"


def test_format_weather_cloudy() -> None:
    assert format_weather(WeatherSnapshot(temp_c=12.0, weather_code=2)) == "12°C ☁"


def test_format_weather_rain() -> None:
    assert format_weather(WeatherSnapshot(temp_c=8.0, weather_code=63)) == "8°C 🌧"


def test_format_weather_snow() -> None:
    assert format_weather(WeatherSnapshot(temp_c=-2.0, weather_code=73)) == "-2°C 🌨"


async def test_weather_poller_patches_ui_state() -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_weather(self, w: str) -> None:
            pushed.append(w)

    client = AsyncMock()
    client.current.return_value = WeatherSnapshot(temp_c=18.4, weather_code=0)

    poller = WeatherPoller(
        FakeUI(),  # type: ignore[arg-type]
        client,
        latitude=52.23,
        longitude=21.01,
    )
    await poller.tick()
    assert pushed == ["18°C ☀"]


def test_format_weather_fog() -> None:
    assert format_weather(WeatherSnapshot(temp_c=5.0, weather_code=45)) == "5°C 🌫"


def test_format_weather_thunderstorm() -> None:
    assert format_weather(WeatherSnapshot(temp_c=22.0, weather_code=95)) == "22°C ⛈"


def test_format_weather_unknown_code_falls_back_to_cloudy() -> None:
    assert format_weather(WeatherSnapshot(temp_c=20.0, weather_code=999)) == "20°C ☁"


async def test_weather_poller_swallows_http_errors() -> None:
    pushed: list[str] = []

    class FakeUI:
        def set_weather(self, w: str) -> None:
            pushed.append(w)

    client = AsyncMock()
    client.current.side_effect = httpx.ConnectError("nope")

    poller = WeatherPoller(
        FakeUI(),  # type: ignore[arg-type]
        client,
        latitude=52.23,
        longitude=21.01,
    )
    await poller.tick()  # must not raise
    assert pushed == []
