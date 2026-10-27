"""A small client for Flexarr's API: the device list, device commands and the playback event stream."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp


class FlexarrError(Exception):
    """Flexarr couldn't be reached, or answered with an error."""


class FlexarrAuthError(FlexarrError):
    """The API key was refused."""


class FlexarrClient:
    """Talks to one Flexarr server with its API key."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self.url}/api/v1{path}",
                headers=self._headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status in (401, 403):
                    raise FlexarrAuthError(await response.text())
                if response.status >= 400:
                    raise FlexarrError(f"{method} {path}: {response.status} {await response.text()}")
                if response.status == 204 or response.content_length == 0:
                    return None
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FlexarrError(f"Couldn't reach Flexarr at {self.url}: {err}") from err

    async def status(self) -> dict[str, Any]:
        """The server's name and version."""
        return await self._request("GET", "/system/status")

    async def devices(self) -> list[dict[str, Any]]:
        """Every Apple TV, iPhone and iPad signed in, with what each is playing."""
        return await self._request("GET", "/devices")

    async def play(self, device_id: str, item_id: str, from_beginning: bool = False) -> dict[str, Any]:
        """Plays a title on a device. A show or season plays the episode the device's profile is up to."""
        return await self._request("POST", f"/devices/{device_id}/play", {"itemId": item_id, "fromBeginning": from_beginning})

    async def command(self, device_id: str, command: str) -> None:
        """Pauses, resumes or stops a device ("pause", "resume", "stop")."""
        await self._request("POST", f"/devices/{device_id}/{command}")

    def image_url(self, path: str | None) -> str | None:
        """An artwork path from the API as a full address."""
        if not path:
            return None
        return path if path.startswith(("http://", "https://")) else f"{self.url}{path}"

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Playback events as they happen, until the connection drops (then it raises FlexarrError)."""
        try:
            async with self._session.get(
                f"{self.url}/api/v1/events",
                headers={**self._headers, "Accept": "text/event-stream"},
                # No overall limit; the server sends a comment every 20 seconds, so a minute of silence means it's gone.
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60),
            ) as response:
                if response.status in (401, 403):
                    raise FlexarrAuthError(await response.text())
                if response.status >= 400:
                    raise FlexarrError(f"GET /events: {response.status}")
                event, data = None, []
                async for raw in response.content:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if not line:
                        if event == "playback" and data:
                            yield json.loads("\n".join(data))
                        event, data = None, []
                    elif line.startswith(":"):
                        continue
                    elif line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
        except (aiohttp.ClientError, TimeoutError) as err:
            raise FlexarrError(f"The event stream from {self.url} dropped: {err}") from err
        raise FlexarrError(f"The event stream from {self.url} ended")
