"""Config flow for PyPLUS integration."""

from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PyPlusApiClient, PyPlusApiError, PyPlusAuthError
from .const import CONF_API_KEY, CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default="http://localhost:8080"): str,
        vol.Required(CONF_API_KEY): str,
    }
)


class PyPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PyPLUS."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = PyPlusApiClient(user_input[CONF_URL], user_input[CONF_API_KEY], session)

            try:
                await client.async_get_health()
            except PyPlusAuthError:
                errors["base"] = "invalid_auth"
            except (PyPlusApiError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during PyPLUS config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="PyPLUS", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
