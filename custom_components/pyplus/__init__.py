"""The PyPLUS integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PyPlusApiClient
from .const import CONF_API_KEY, CONF_URL, DOMAIN
from .coordinator import PyPlusCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PyPLUS from a config entry."""
    session = async_get_clientsession(hass)
    client = PyPlusApiClient(entry.data[CONF_URL], entry.data[CONF_API_KEY], session)

    coordinator = PyPlusCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def handle_set_weekmenu_slot(call: ServiceCall) -> None:
        await client.async_set_weekmenu_slot(
            call.data["slot"],
            call.data["week_start"],
            call.data.get("dish_id"),
        )
        await coordinator.async_request_refresh()

    async def handle_trigger_autopilot(call: ServiceCall) -> None:
        await client.async_trigger_autopilot()
        await coordinator.async_request_refresh()

    async def handle_sync_now(call: ServiceCall) -> None:
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "set_weekmenu_slot",
        handle_set_weekmenu_slot,
        schema=vol.Schema(
            {
                vol.Required("slot"): cv.string,
                vol.Required("week_start"): cv.string,
                vol.Optional("dish_id"): vol.Any(int, None),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN, "trigger_autopilot", handle_trigger_autopilot
    )

    hass.services.async_register(DOMAIN, "sync_now", handle_sync_now)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
