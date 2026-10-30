"""Fixtures: a pretend Flexarr server behind FlexarrClient."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_API_KEY, CONF_URL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flexarr.api import FlexarrNotOpenError
from custom_components.flexarr.const import DOMAIN

URL = "http://flexarr.test:8383"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Loads custom_components/ in every test."""
    yield


def heat(paused: bool = False) -> dict[str, Any]:
    """The living room TV, playing Heat an hour in."""
    return {
        "id": "tv1",
        "name": "Living room TV",
        "online": True,
        "lastUsedAt": "2026-10-27T20:00:00Z",
        "profileId": "default",
        "profileName": "Dan",
        "isThisOne": False,
        "nowPlaying": {
            "item": {
                "id": "item-heat",
                "kind": "Movie",
                "title": "Heat",
                "seriesTitle": None,
                "seasonNumber": None,
                "episodeNumber": None,
                "artwork": {"poster": "/api/v1/images/heat/poster", "thumb": None},
            },
            "positionSeconds": 3600.0,
            "durationSeconds": 10200.0,
            "paused": paused,
        },
    }


class FakeFlexarr:
    """What the integration sees of the server: the device list, commands sent, and events to push."""

    def __init__(self) -> None:
        self.device_list: list[dict[str, Any]] = [heat()]
        self.commands: list[tuple[str, str]] = []
        self.played: list[tuple[str, str]] = []
        self.sounds: list[tuple[str, dict[str, str | None]]] = []
        self.closed: set[str] = set()
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def sound(self, device: str, **settings: str | None) -> None:
        if device in self.closed:
            raise FlexarrNotOpenError("Flexarr isn't open")
        self.sounds.append((device, settings))

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self.queue.get()


@pytest.fixture
def flexarr() -> FakeFlexarr:
    fake = FakeFlexarr()
    with (
        patch("custom_components.flexarr.api.FlexarrClient.status", AsyncMock(return_value={"appName": "Flexarr", "version": "0.39.0"})),
        patch("custom_components.flexarr.api.FlexarrClient.devices", AsyncMock(side_effect=lambda: fake.device_list)),
        patch(
            "custom_components.flexarr.api.FlexarrClient.command",
            AsyncMock(side_effect=lambda device, command: fake.commands.append((device, command))),
        ),
        patch(
            "custom_components.flexarr.api.FlexarrClient.play",
            AsyncMock(side_effect=lambda device, item, from_beginning=False: fake.played.append((device, item)) or {}),
        ),
        patch("custom_components.flexarr.api.FlexarrClient.sound", AsyncMock(side_effect=fake.sound)),
        patch("custom_components.flexarr.api.FlexarrClient.events", lambda self: fake.events()),
    ):
        yield fake


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, title="Flexarr", unique_id=URL, data={CONF_URL: URL, CONF_API_KEY: "key"})
