"""The integration end to end, against a pretend server."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.components import automation
from homeassistant.components.media_player import ATTR_MEDIA_CONTENT_ID, ATTR_MEDIA_CONTENT_TYPE, ATTR_MEDIA_TITLE
from homeassistant.const import ATTR_ENTITY_ID, CONF_API_KEY, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.flexarr.api import FlexarrAuthError, FlexarrError
from custom_components.flexarr.const import DOMAIN, EVENT_PLAYBACK

from .conftest import URL, FakeFlexarr, heat

PLAYER = "media_player.living_room_tv"


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setting_up_checks_the_key(hass: HomeAssistant, flexarr: FakeFlexarr) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.flexarr.api.FlexarrClient.devices", AsyncMock(side_effect=FlexarrAuthError("no"))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL, CONF_API_KEY: "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}

    with patch("custom_components.flexarr.api.FlexarrClient.status", AsyncMock(side_effect=FlexarrError("down"))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL, CONF_API_KEY: "key"})
    assert result["errors"] == {"base": "cannot_connect"}

    with patch("custom_components.flexarr.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL + "/", CONF_API_KEY: " key "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: URL, CONF_API_KEY: "key"}


async def test_a_device_is_a_media_player(hass: HomeAssistant, flexarr: FakeFlexarr, entry: MockConfigEntry) -> None:
    await _set_up(hass, entry)

    state = hass.states.get(PLAYER)
    assert state.state == "playing"
    assert state.attributes[ATTR_MEDIA_TITLE] == "Heat"
    assert state.attributes[ATTR_MEDIA_CONTENT_TYPE] == "movie"
    assert state.attributes[ATTR_MEDIA_CONTENT_ID] == "item-heat"
    assert state.attributes["media_duration"] == 10200
    assert state.attributes["profile"] == "Dan"

    await hass.services.async_call("media_player", "media_pause", {ATTR_ENTITY_ID: PLAYER}, blocking=True)
    await hass.services.async_call("media_player", "media_play", {ATTR_ENTITY_ID: PLAYER}, blocking=True)
    await hass.services.async_call("media_player", "media_stop", {ATTR_ENTITY_ID: PLAYER}, blocking=True)
    assert flexarr.commands == [("tv1", "pause"), ("tv1", "resume"), ("tv1", "stop")]

    await hass.services.async_call(
        "media_player",
        "play_media",
        {ATTR_ENTITY_ID: PLAYER, ATTR_MEDIA_CONTENT_ID: "item-show", ATTR_MEDIA_CONTENT_TYPE: "tvshow"},
        blocking=True,
    )
    assert flexarr.played == [("tv1", "item-show")]


async def test_nothing_playing_is_idle_and_closed_is_off(hass: HomeAssistant, flexarr: FakeFlexarr, entry: MockConfigEntry) -> None:
    flexarr.device_list = [{**heat(), "nowPlaying": None}]
    await _set_up(hass, entry)
    assert hass.states.get(PLAYER).state == "idle"

    flexarr.device_list = [{**heat(), "nowPlaying": None, "online": False}]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(PLAYER).state == "off"


async def test_playback_events_fire_and_trigger_automations(hass: HomeAssistant, flexarr: FakeFlexarr, entry: MockConfigEntry) -> None:
    await _set_up(hass, entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "tv1")})
    assert device is not None
    fired = async_capture_events(hass, EVENT_PLAYBACK)
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: {
                "trigger": {"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": "credits"},
                "action": {"event": "lights_up", "event_data": {"title": "{{ trigger.event.data.title }}"}},
            }
        },
    )
    lights_up = async_capture_events(hass, "lights_up")

    # The film pauses: the player follows, and the event goes out.
    flexarr.device_list = [heat(paused=True)]
    await flexarr.queue.put(
        {
            "kind": "Paused",
            "sessionId": "s1",
            "deviceId": "tv1",
            "deviceName": "Living room TV",
            "profileId": "default",
            "profileName": "Dan",
            "item": heat()["nowPlaying"]["item"],
            "positionSeconds": 3600.0,
            "durationSeconds": 10200.0,
        }
    )
    await hass.async_block_till_done()
    assert fired[-1].data["type"] == "paused"
    assert fired[-1].data["device_id"] == device.id
    assert fired[-1].data["media_type"] == "movie"
    assert hass.states.get(PLAYER).state == "paused"
    assert not lights_up

    await flexarr.queue.put({"kind": "Credits", "sessionId": "s1", "deviceId": "tv1", "item": heat()["nowPlaying"]["item"]})
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert [event.data["title"] for event in lights_up] == ["Heat"]


async def test_a_device_signed_in_later_gets_a_player(hass: HomeAssistant, flexarr: FakeFlexarr, entry: MockConfigEntry) -> None:
    await _set_up(hass, entry)
    flexarr.device_list = [heat(), {**heat(), "id": "ipad", "name": "Kitchen iPad", "nowPlaying": None}]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("media_player.kitchen_ipad").state == "idle"


async def test_the_player_follows_events_without_waiting_for_a_fetch(
    hass: HomeAssistant, flexarr: FakeFlexarr, entry: MockConfigEntry
) -> None:
    await _set_up(hass, entry)
    item = heat()["nowPlaying"]["item"]
    # Fetches are throttled to one every ten seconds; the events alone must carry the player.
    with patch("custom_components.flexarr.coordinator.FlexarrCoordinator.async_request_refresh", AsyncMock()):
        await flexarr.queue.put({"kind": "Paused", "deviceId": "tv1", "item": item, "positionSeconds": 3700.0, "durationSeconds": 10200.0})
        await hass.async_block_till_done()
        state = hass.states.get(PLAYER)
        assert state.state == "paused"
        assert state.attributes["media_position"] == 3700

        await flexarr.queue.put({"kind": "Resumed", "deviceId": "tv1", "item": item, "positionSeconds": 3700.0, "durationSeconds": 10200.0})
        await hass.async_block_till_done()
        assert hass.states.get(PLAYER).state == "playing"

        await flexarr.queue.put({"kind": "Stopped", "deviceId": "tv1", "item": item, "positionSeconds": 3710.0, "durationSeconds": 10200.0})
        await hass.async_block_till_done()
        assert hass.states.get(PLAYER).state == "idle"
