"""Each Apple TV, iPhone and iPad signed in to Flexarr, as a media player."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import FlexarrError, FlexarrNotOpenError
from .const import DIALOGUE_BOOST, DOMAIN, NIGHT_MODE, SPEAKERS
from .coordinator import FlexarrConfigEntry, FlexarrCoordinator, media_type


async def async_setup_entry(hass: HomeAssistant, entry: FlexarrConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    """Adds a player for every device, and for each one signed in later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [FlexarrPlayer(coordinator, device_id) for device_id in coordinator.data if device_id not in known]
        known.update(player.device_id for player in new)
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))

    # flexarr.set_sound: night mode on in the lounge when the lights dim, say.
    entity_platform.async_get_current_platform().async_register_entity_service(
        "set_sound",
        {
            vol.Optional("dialogue_boost"): vol.In(DIALOGUE_BOOST),
            vol.Optional("night_mode"): vol.In(NIGHT_MODE),
            vol.Optional("speakers"): vol.In(SPEAKERS),
        },
        "async_set_sound",
    )


class FlexarrPlayer(CoordinatorEntity[FlexarrCoordinator], MediaPlayerEntity):
    """A device's player: what it's playing, and play, pause and stop. Off when Flexarr isn't open on it."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_media_image_remotely_accessible = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.STOP | MediaPlayerEntityFeature.PLAY_MEDIA
    )

    def __init__(self, coordinator: FlexarrCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = device_id
        device = coordinator.data[device_id]
        name = device["name"]
        self._attr_device_class = MediaPlayerDeviceClass.TV if "tv" in name.lower() else MediaPlayerDeviceClass.RECEIVER
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)}, name=name, manufacturer="Flexarr", model="Flexarr app")
        self._update_position()

    @property
    def _device(self) -> dict[str, Any] | None:
        return self.coordinator.data.get(self.device_id)

    @property
    def _playing(self) -> dict[str, Any] | None:
        return (self._device or {}).get("nowPlaying")

    @property
    def _item(self) -> dict[str, Any]:
        return (self._playing or {}).get("item") or {}

    @property
    def available(self) -> bool:
        # A device that signed out drops out of the list.
        return super().available and self._device is not None

    @property
    def state(self) -> MediaPlayerState:
        if playing := self._playing:
            return MediaPlayerState.PAUSED if playing.get("paused") else MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE if (self._device or {}).get("online") else MediaPlayerState.OFF

    @property
    def media_content_id(self) -> str | None:
        return self._item.get("id")

    @property
    def media_content_type(self) -> str | None:
        return media_type(self._item.get("kind"))

    @property
    def media_title(self) -> str | None:
        return self._item.get("title")

    @property
    def media_series_title(self) -> str | None:
        return self._item.get("seriesTitle")

    @property
    def media_season(self) -> str | None:
        season = self._item.get("seasonNumber")
        return None if season is None else str(season)

    @property
    def media_episode(self) -> str | None:
        episode = self._item.get("episodeNumber")
        return None if episode is None else str(episode)

    @property
    def media_artist(self) -> str | None:
        return self._item.get("trackArtist")

    @property
    def media_duration(self) -> int | None:
        duration = (self._playing or {}).get("durationSeconds")
        return int(duration) if duration else None

    @property
    def media_image_url(self) -> str | None:
        artwork = self._item.get("artwork") or {}
        return self.coordinator.client.image_url(artwork.get("thumb") or artwork.get("poster"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device or {}
        return {"profile": device.get("profileName"), "flexarr_device_id": self.device_id}

    def _update_position(self) -> None:
        position = (self._playing or {}).get("positionSeconds")
        if position is None:
            self._attr_media_position = None
            self._attr_media_position_updated_at = None
        elif position != self._attr_media_position:
            self._attr_media_position = int(position)
            self._attr_media_position_updated_at = dt_util.utcnow()

    @callback
    def _handle_coordinator_update(self) -> None:
        if device := self._device:
            self._update_device_name(device["name"])
        self._update_position()
        super()._handle_coordinator_update()

    def _update_device_name(self, name: str) -> None:
        if self.device_entry and self.device_entry.name != name:
            dr.async_get(self.hass).async_update_device(self.device_entry.id, name=name)

    async def _send(self, command: str) -> None:
        try:
            await self.coordinator.client.command(self.device_id, command)
        except FlexarrError as err:
            raise HomeAssistantError(f"Flexarr couldn't {command} {self.name}: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._send("resume")

    async def async_media_pause(self) -> None:
        await self._send("pause")

    async def async_media_stop(self) -> None:
        await self._send("stop")

    async def async_set_sound(self, dialogue_boost: str | None = None, night_mode: str | None = None, speakers: str | None = None) -> None:
        """Changes the device's dialogue boost, night mode or speakers, while Flexarr is open on it."""
        if not (dialogue_boost or night_mode or speakers):
            raise HomeAssistantError("Choose a dialogue boost, night mode or speakers to change.")
        try:
            await self.coordinator.client.sound(
                self.device_id,
                dialogue_boost=dialogue_boost and dialogue_boost.capitalize(),
                night_mode=night_mode and night_mode.capitalize(),
                speakers=speakers and speakers.capitalize(),
            )
        except FlexarrNotOpenError as err:
            raise HomeAssistantError(f"Flexarr isn't open on {self.name}.") from err
        except FlexarrError as err:
            raise HomeAssistantError(f"Flexarr couldn't change the sound on {self.name}: {err}") from err

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """Plays a Flexarr title by its id; a show's id plays the episode the device's profile is up to."""
        try:
            await self.coordinator.client.play(self.device_id, media_id)
        except FlexarrError as err:
            raise HomeAssistantError(f"Flexarr couldn't play {media_id} on {self.name}: {err}") from err
        await self.coordinator.async_request_refresh()
