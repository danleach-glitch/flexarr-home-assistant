"""Flexarr: its Apple TVs, iPhones and iPads as media players, and playback events for automations."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FlexarrClient
from .coordinator import FlexarrConfigEntry, FlexarrCoordinator

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: FlexarrConfigEntry) -> bool:
    """Connects to the server, then follows its events in the background."""
    client = FlexarrClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_KEY])
    coordinator = FlexarrCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, coordinator.listen(), f"flexarr events {client.url}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FlexarrConfigEntry) -> bool:
    """The background listener is cancelled with the entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
