"""Set up Flexarr from the UI: the server's address and its API key (Settings › Access in Flexarr)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import FlexarrAuthError, FlexarrClient, FlexarrError
from .const import DOMAIN

USER_SCHEMA = vol.Schema({vol.Required(CONF_URL, default="http://"): str, vol.Required(CONF_API_KEY): str})
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


class FlexarrConfigFlow(ConfigFlow, domain=DOMAIN):
    """Asks for the server and key, and checks them before saving."""

    VERSION = 1

    async def _check(self, url: str, api_key: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
        client = FlexarrClient(async_get_clientsession(self.hass), url, api_key)
        try:
            status = await client.status()
            # The status is open to the home network; the device list proves the key.
            await client.devices()
        except FlexarrAuthError:
            return None, {"base": "invalid_auth"}
        except FlexarrError:
            return None, {"base": "cannot_connect"}
        return status, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            status, errors = await self._check(url, user_input[CONF_API_KEY].strip())
            if status is not None:
                return self.async_create_entry(
                    title=status.get("appName") or "Flexarr",
                    data={CONF_URL: url, CONF_API_KEY: user_input[CONF_API_KEY].strip()},
                )
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            status, errors = await self._check(entry.data[CONF_URL], user_input[CONF_API_KEY].strip())
            if status is not None:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: user_input[CONF_API_KEY].strip()})
        return self.async_show_form(step_id="reauth_confirm", data_schema=REAUTH_SCHEMA, errors=errors)
