import asyncio

import pytest

from avelren import collector
from avelren.config import (
    CollectorConfigurationError,
    Settings,
    validate_collector_settings,
)


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "echerha_base_url": "https://back.echerha.gov.ua/api",
        "echerha_vehicle_type": 1,
        "poll_interval_seconds": 60,
        "http_timeout_seconds": 15,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_collector_settings_are_valid() -> None:
    validate_collector_settings(make_settings())


@pytest.mark.parametrize("timeout", [1, 30])
def test_accepts_inclusive_http_timeout_boundaries(timeout: int) -> None:
    validate_collector_settings(make_settings(http_timeout_seconds=timeout))


@pytest.mark.parametrize(
    "url",
    [
        "http://back.echerha.gov.ua/api",
        "https://echerha.gov.ua/api",
        "https://back.echerha.gov.ua:443/api",
        "https://back.echerha.gov.ua/v4",
        "https://back.echerha.gov.ua/api/",
        "https://back.echerha.gov.ua/api?vehicle=1",
        "https://back.echerha.gov.ua/api#fragment",
        "https://guest@back.echerha.gov.ua/api",
    ],
)
def test_rejects_noncanonical_echerha_base_url(url: str) -> None:
    with pytest.raises(
        CollectorConfigurationError,
        match=r"^invalid collector setting: echerha_base_url$",
    ):
        validate_collector_settings(make_settings(echerha_base_url=url))


@pytest.mark.parametrize("vehicle_type", [0, 2])
def test_rejects_non_truck_vehicle_type(vehicle_type: int) -> None:
    with pytest.raises(
        CollectorConfigurationError,
        match=r"^invalid collector setting: echerha_vehicle_type$",
    ):
        validate_collector_settings(make_settings(echerha_vehicle_type=vehicle_type))


@pytest.mark.parametrize("interval", [59, 61])
def test_rejects_non_sixty_second_cadence(interval: int) -> None:
    with pytest.raises(
        CollectorConfigurationError,
        match=r"^invalid collector setting: poll_interval_seconds$",
    ):
        validate_collector_settings(make_settings(poll_interval_seconds=interval))


@pytest.mark.parametrize("timeout", [0, 31])
def test_rejects_unsafe_http_timeout(timeout: int) -> None:
    with pytest.raises(
        CollectorConfigurationError,
        match=r"^invalid collector setting: http_timeout_seconds$",
    ):
        validate_collector_settings(make_settings(http_timeout_seconds=timeout))


def test_invalid_startup_stops_before_database_or_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector.settings, "poll_interval_seconds", 59)

    def unexpected_side_effect(*_args: object, **_kwargs: object) -> None:
        pytest.fail("collector startup reached a database or HTTP side effect")

    monkeypatch.setattr(collector, "get_pool", unexpected_side_effect)
    monkeypatch.setattr(collector.httpx, "AsyncClient", unexpected_side_effect)

    with pytest.raises(CollectorConfigurationError):
        asyncio.run(collector.main())
