"""DataUpdateCoordinator for PyPLUS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PyPlusApiClient, PyPlusApiError, PyPlusAuthError
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class PyPlusData:
    """Data returned by the coordinator."""

    status: dict = field(default_factory=dict)
    weekmenu: dict | None = None
    staples: list | None = None
    autopilot: dict | None = None
    settings: dict | None = None


class PyPlusCoordinator(DataUpdateCoordinator[PyPlusData]):
    """Coordinator that polls the PyPLUS API."""

    def __init__(self, hass: HomeAssistant, client: PyPlusApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="pyplus",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> PyPlusData:
        try:
            status_resp = await self.client.async_get_status()
            weekmenu_resp = await self.client.async_get_weekmenu()
            staples_resp = await self.client.async_get_staples()
            autopilot_resp = await self.client.async_get_autopilot_plan()
            settings_resp = await self.client.async_get_settings()
        except PyPlusAuthError as err:
            raise ConfigEntryAuthFailed from err
        except PyPlusApiError as err:
            raise UpdateFailed(f"Error communicating with PyPLUS: {err}") from err

        return PyPlusData(
            status=status_resp.get("data", {}),
            weekmenu=weekmenu_resp.get("data"),
            staples=staples_resp.get("data"),
            autopilot=autopilot_resp.get("data"),
            settings=settings_resp.get("data"),
        )
