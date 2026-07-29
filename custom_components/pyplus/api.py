"""API client for the PyPLUS REST API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class PyPlusApiError(Exception):
    pass


class PyPlusAuthError(PyPlusApiError):
    pass


class PyPlusApiClient:
    def __init__(self, host: str, api_key: str, session: aiohttp.ClientSession) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def _get(self, path: str, **params: Any) -> dict:
        url = f"{self._host}/api/v1{path}"
        try:
            async with self._session.get(url, headers=self._headers, params=params) as resp:
                if resp.status == 401:
                    raise PyPlusAuthError("Invalid API key")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PyPlusApiError(f"Error communicating with PyPLUS: {err}") from err

    async def _post(self, path: str, json: dict | None = None) -> dict:
        url = f"{self._host}/api/v1{path}"
        try:
            async with self._session.post(url, headers=self._headers, json=json) as resp:
                if resp.status == 401:
                    raise PyPlusAuthError("Invalid API key")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PyPlusApiError(f"Error communicating with PyPLUS: {err}") from err

    async def _put(self, path: str, json: dict | None = None) -> dict:
        url = f"{self._host}/api/v1{path}"
        try:
            async with self._session.put(url, headers=self._headers, json=json) as resp:
                if resp.status == 401:
                    raise PyPlusAuthError("Invalid API key")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PyPlusApiError(f"Error communicating with PyPLUS: {err}") from err

    async def _patch(self, path: str, json: dict | None = None) -> dict:
        url = f"{self._host}/api/v1{path}"
        try:
            async with self._session.patch(url, headers=self._headers, json=json) as resp:
                if resp.status == 401:
                    raise PyPlusAuthError("Invalid API key")
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PyPlusApiError(f"Error communicating with PyPLUS: {err}") from err

    async def async_get_health(self) -> dict:
        url = f"{self._host}/api/v1/health"
        try:
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise PyPlusApiError(f"Cannot connect to PyPLUS: {err}") from err

    async def async_get_status(self) -> dict:
        return await self._get("/status")

    async def async_get_weekmenu(self, week: str | None = None) -> dict:
        params = {}
        if week:
            params["week"] = week
        return await self._get("/weekmenu", **params)

    async def async_get_staples(self) -> dict:
        return await self._get("/staples")

    async def async_get_autopilot_plan(self) -> dict:
        return await self._get("/autopilot/plan")

    async def async_get_settings(self) -> dict:
        return await self._get("/settings")

    async def async_patch_settings(self, patch: dict) -> dict:
        return await self._patch("/settings", json=patch)

    async def async_set_weekmenu_slot(
        self, slot: str, week_start: str, dish_id: int | None
    ) -> dict:
        return await self._put(
            "/weekmenu/slot",
            json={"slot": slot, "week_start": week_start, "dish_id": dish_id},
        )

    async def async_trigger_autopilot(self) -> dict:
        return await self._post("/autopilot/prepare")

    async def async_trigger_job(self, name: str) -> dict:
        return await self._post(f"/jobs/{name}/run")
