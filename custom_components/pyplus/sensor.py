"""Sensor entities for PyPLUS."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SLOT_TO_WEEKDAY
from .coordinator import PyPlusCoordinator, PyPlusData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PyPlusCoordinator = entry.runtime_data
    async_add_entities(
        [
            PyPlusWeekMenuTodaySensor(coordinator, entry),
            PyPlusWeekMenuFilledSensor(coordinator, entry),
            PyPlusAutopilotStatusSensor(coordinator, entry),
            PyPlusStaplesCountSensor(coordinator, entry),
        ]
    )


class PyPlusSensorBase(CoordinatorEntity[PyPlusCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PyPlusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "PyPLUS",
            "manufacturer": "PyPLUS",
        }


class PyPlusWeekMenuTodaySensor(PyPlusSensorBase):
    _attr_name = "Weekmenu vandaag"
    _attr_icon = "mdi:food"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_weekmenu_today"

    @property
    def native_value(self) -> str | None:
        data: PyPlusData = self.coordinator.data
        if not data or not data.weekmenu:
            return None
        today = date.today()
        slots = data.weekmenu.get("slots", [])
        for slot in slots:
            slot_name = slot.get("slot", "")
            weekday = SLOT_TO_WEEKDAY.get(slot_name)
            if weekday is not None and weekday == today.weekday() and slot.get("dish"):
                return slot["dish"]["name"]
        return None

    @property
    def extra_state_attributes(self) -> dict:
        data: PyPlusData = self.coordinator.data
        if not data or not data.weekmenu:
            return {}
        attrs = {}
        for slot in data.weekmenu.get("slots", []):
            dish = slot.get("dish")
            attrs[slot["slot"]] = dish["name"] if dish else None
        return attrs


class PyPlusWeekMenuFilledSensor(PyPlusSensorBase):
    _attr_name = "Weekmenu gevuld"
    _attr_icon = "mdi:calendar-check"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_weekmenu_filled"

    @property
    def native_value(self) -> int:
        data: PyPlusData = self.coordinator.data
        if not data or not data.weekmenu:
            return 0
        return sum(1 for s in data.weekmenu.get("slots", []) if s.get("dish"))

    @property
    def extra_state_attributes(self) -> dict:
        data: PyPlusData = self.coordinator.data
        if not data or not data.weekmenu:
            return {}
        return {
            s["slot"]: s["dish"]["name"] if s.get("dish") else None
            for s in data.weekmenu.get("slots", [])
        }


class PyPlusAutopilotStatusSensor(PyPlusSensorBase):
    _attr_name = "Autopilot status"
    _attr_icon = "mdi:robot"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_autopilot_status"

    @property
    def native_value(self) -> str:
        data: PyPlusData = self.coordinator.data
        if not data or not data.autopilot:
            return "none"
        return data.autopilot.get("status", "none")

    @property
    def extra_state_attributes(self) -> dict:
        data: PyPlusData = self.coordinator.data
        if not data or not data.autopilot:
            return {}
        plan = data.autopilot
        return {
            "week_start": plan.get("week_start"),
            "created_at": plan.get("created_at"),
        }


class PyPlusStaplesCountSensor(PyPlusSensorBase):
    _attr_name = "Vaste boodschappen"
    _attr_icon = "mdi:basket"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_staples_count"

    @property
    def native_value(self) -> int:
        data: PyPlusData = self.coordinator.data
        if not data or not data.staples:
            return 0
        return len(data.staples)
