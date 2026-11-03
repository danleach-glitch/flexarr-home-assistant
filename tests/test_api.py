"""The client's reading of the event stream, against a pretend response."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.flexarr.api import FlexarrClient, FlexarrError


def _client(lines: list[bytes]) -> FlexarrClient:
    response = MagicMock(status=200)

    async def content() -> Any:
        for line in lines:
            yield line

    response.content = content()

    @asynccontextmanager
    async def get(*args: Any, **kwargs: Any) -> Any:
        yield response

    session = MagicMock()
    session.get = get
    return FlexarrClient(session, "http://flexarr.local:8383", "key")


async def test_malformed_events_are_skipped_and_the_stream_goes_on() -> None:
    client = _client(
        [
            b"event: playback\n",
            b"data: {not json\n",
            b"\n",
            b"event: playback\n",
            b'data: {"deviceId": "tv1"}\n',
            b"\n",
            b"event: playback\n",
            b"data: [1, 2]\n",
            b"\n",
            b"event: playback\n",
            b"data: \xff\xfe\n",
            b"\n",
            b": keep-alive\n",
            b"event: playback\n",
            b'data: {"kind": "Paused", "deviceId": "tv1"}\n',
            b"\n",
        ]
    )
    events = []
    with pytest.raises(FlexarrError, match="ended"):
        async for event in client.events():
            events.append(event)
    assert events == [{"kind": "Paused", "deviceId": "tv1"}]
