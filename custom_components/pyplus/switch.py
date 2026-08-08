"""Switch entities for PyPLUS."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PyPlusCoordinator, PyPlusData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PyPlusCoordinator = entry.runtime_data
    async_add_entities([PyPlusAutopilotSwitch(coordinator, entry)])


class PyPlusAutopilotSwitch(CoordinatorEntity[PyPlusCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Autopilot"
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator: PyPlusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_autopilot_switch"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "PyPLUS",
            "manufacturer": "PyPLUS",
        }

    @property
    def is_on(self) -> bool:
        data: PyPlusData = self.coordinator.data
        if not data or not data.settings:
            return False
        return bool(data.settings.get("ml_autopilot", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_patch_settings({"ml_autopilot": True})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.client.async_patch_settings({"ml_autopilot": False})
        await self.coordinator.async_request_refresh()
