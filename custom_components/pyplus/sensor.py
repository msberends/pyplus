"""Sensor entities for PyPLUS."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SLOT_TO_WEEKDAY, WEEKDAY_SLOTS
from .coordinator import PyPlusCoordinator, PyPlusData

_DAY_LABELS = {
    "ma": "Maandag",
    "di": "Dinsdag",
    "wo": "Woensdag",
    "do": "Donderdag",
    "vr": "Vrijdag",
    "za": "Zaterdag",
    "zo": "Zondag",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PyPlusCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        PyPlusWeekMenuTodaySensor(coordinator, entry),
        PyPlusWeekMenuFilledSensor(coordinator, entry),
        PyPlusAutopilotStatusSensor(coordinator, entry),
        PyPlusStaplesCountSensor(coordinator, entry),
        PyPlusDishesCountSensor(coordinator, entry),
    ]
    for day in WEEKDAY_SLOTS:
        entities.append(PyPlusWeekMenuDaySensor(coordinator, entry, day))
    async_add_entities(entities)


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

    def _get_slot_dish(self, slot_name: str) -> dict | None:
        data: PyPlusData = self.coordinator.data
        if not data or not data.weekmenu:
            return None
        for slot in data.weekmenu.get("slots", []):
            if slot.get("slot") == slot_name and slot.get("dish"):
                return slot["dish"]
        return None


class PyPlusWeekMenuTodaySensor(PyPlusSensorBase):
    _attr_name = "Weekmenu vandaag"
    _attr_icon = "mdi:food"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_weekmenu_today"

    @property
    def native_value(self) -> str | None:
        today = date.today()
        for slot_name, weekday in SLOT_TO_WEEKDAY.items():
            if weekday == today.weekday():
                dish = self._get_slot_dish(slot_name)
                return dish["name"] if dish else None
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


class PyPlusWeekMenuDaySensor(PyPlusSensorBase):
    """One sensor per weekday — state is the dish name."""

    _attr_icon = "mdi:silverware-fork-knife"

    def __init__(
        self, coordinator: PyPlusCoordinator, entry: ConfigEntry, day: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._day = day
        self._attr_name = f"Weekmenu {_DAY_LABELS[day]}"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_weekmenu_{self._day}"

    @property
    def native_value(self) -> str | None:
        dish = self._get_slot_dish(self._day)
        return dish["name"] if dish else None

    @property
    def extra_state_attributes(self) -> dict:
        dish = self._get_slot_dish(self._day)
        if not dish:
            return {}
        return {
            "dish_id": dish.get("id"),
            "meat_type": dish.get("meat_type"),
            "starch_type": dish.get("starch_type"),
            "prep_minutes": dish.get("prep_minutes"),
            "group_name": dish.get("group_name"),
        }


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

    @property
    def extra_state_attributes(self) -> dict:
        data: PyPlusData = self.coordinator.data
        if not data or not data.staples:
            return {}
        return {
            "products": [
                {
                    "sku": s["sku"],
                    "name": s["display_name"],
                    "qty": s["default_qty"],
                    "every_n_weeks": s["every_n_weeks"],
                }
                for s in data.staples
            ],
        }


class PyPlusDishesCountSensor(PyPlusSensorBase):
    _attr_name = "Gerechten"
    _attr_icon = "mdi:chef-hat"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_dishes_count"

    @property
    def native_value(self) -> int:
        data: PyPlusData = self.coordinator.data
        if not data or not data.dishes:
            return 0
        return len(data.dishes)

    @property
    def extra_state_attributes(self) -> dict:
        data: PyPlusData = self.coordinator.data
        if not data or not data.dishes:
            return {}
        return {
            "dishes": [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "meat_type": d.get("meat_type"),
                    "prep_minutes": d.get("prep_minutes"),
                    "group_name": d.get("group_name"),
                    "rating": d.get("rating"),
                }
                for d in data.dishes
            ],
        }
