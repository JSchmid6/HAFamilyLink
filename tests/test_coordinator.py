"""Unit tests for FamilyLinkDataUpdateCoordinator and parsing helpers."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import pure parsing functions directly – no homeassistant dependency
from custom_components.familylink.client.parsers import parse_restrictions, parse_usage

from .conftest import (
	CHILD_ID_1,
	CHILD_ID_2,
	MOCK_CHILDREN,
	make_raw_apps_and_usage,
)

# Coordinator is imported after stubs are in place (conftest injects them)
from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator

# ---------------------------------------------------------------------------
# parse_usage unit tests
# ---------------------------------------------------------------------------


class TestParseUsage:
	"""Tests for the parse_usage helper."""

	def test_returns_today_sessions_only(self) -> None:
		"""Sessions from other days must be excluded."""
		today = date.today()
		raw: dict[str, Any] = {
			"apps": [{"packageName": "com.example.app", "title": "My App"}],
			"appUsageSessions": [
				{
					"appId": {"androidAppPackageName": "com.example.app"},
					"usage": "100s",
					"date": {"year": today.year, "month": today.month, "day": today.day},
				},
				# Yesterday – should be excluded
				{
					"appId": {"androidAppPackageName": "com.example.app"},
					"usage": "9999s",
					"date": {"year": 2000, "month": 1, "day": 1},
				},
			],
		}
		result = parse_usage(raw)
		assert len(result) == 1
		assert result[0]["usage_seconds"] == 100

	def test_resolves_package_name_to_title(self) -> None:
		"""Package names should be resolved to human-readable titles."""
		raw = make_raw_apps_and_usage()
		result = parse_usage(raw)
		names = {item["app_name"] for item in result}
		assert "YouTube" in names
		assert "Chrome" in names

	def test_sorted_by_usage_descending(self) -> None:
		"""Result must be sorted by usage_seconds descending."""
		raw = make_raw_apps_and_usage()
		result = parse_usage(raw)
		assert result[0]["usage_seconds"] >= result[-1]["usage_seconds"]

	def test_empty_sessions(self) -> None:
		"""No sessions should return an empty list."""
		raw: dict[str, Any] = {"apps": [], "appUsageSessions": []}
		assert parse_usage(raw) == []

	def test_malformed_duration_defaults_to_zero(self) -> None:
		"""Non-numeric usage strings should be treated as 0 seconds."""
		today = date.today()
		raw: dict[str, Any] = {
			"apps": [],
			"appUsageSessions": [
				{
					"appId": {"androidAppPackageName": "com.example"},
					"usage": "NaN",
					"date": {"year": today.year, "month": today.month, "day": today.day},
				}
			],
		}
		result = parse_usage(raw)
		assert result[0]["usage_seconds"] == 0


# ---------------------------------------------------------------------------
# parse_restrictions unit tests
# ---------------------------------------------------------------------------


class TestParseRestrictions:
	"""Tests for the parse_restrictions helper."""

	def test_blocked_app_classification(self) -> None:
		"""Apps with hidden=True must appear in 'blocked'."""
		raw = make_raw_apps_and_usage()
		result = parse_restrictions(raw)
		assert "TikTok" in result["blocked"]

	def test_limited_app_classification(self) -> None:
		"""Apps with usageLimit must appear in 'limited' with limit_minutes."""
		raw = make_raw_apps_and_usage()
		result = parse_restrictions(raw)
		limited_names = [item["app"] for item in result["limited"]]
		assert "YouTube" in limited_names
		youtube = next(i for i in result["limited"] if i["app"] == "YouTube")
		assert youtube["limit_minutes"] == 60

	def test_unrestricted_app_not_in_any_list(self) -> None:
		"""Chrome has no restriction – it should not appear in any list."""
		raw = make_raw_apps_and_usage()
		result = parse_restrictions(raw)
		all_apps = (
			[i["app"] for i in result["limited"]]
			+ result["blocked"]
			+ result["always_allowed"]
		)
		assert "Chrome" not in all_apps

	def test_always_allowed_classification(self) -> None:
		"""Apps with alwaysAllowedState=alwaysAllowedStateEnabled go to always_allowed."""
		raw: dict[str, Any] = {
			"apps": [
				{
					"packageName": "com.example.maps",
					"title": "Maps",
					"supervisionSetting": {
						"alwaysAllowedAppInfo": {
							"alwaysAllowedState": "alwaysAllowedStateEnabled"
						}
					},
				}
			],
			"appUsageSessions": [],
		}
		result = parse_restrictions(raw)
		assert "Maps" in result["always_allowed"]

	def test_empty_raw(self) -> None:
		"""Empty response should return empty lists."""
		result = parse_restrictions({})
		assert result == {"limited": [], "blocked": [], "always_allowed": []}


# ---------------------------------------------------------------------------
# Coordinator integration tests (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCoordinatorUpdate:
	"""Integration-level tests for _async_update_data."""

	async def test_data_structure_returned(
		self, mock_config_entry: MagicMock, mock_client: AsyncMock
	) -> None:
		"""Coordinator data must have children / usage / restrictions keys."""
		hass = MagicMock()
		hass.data = {}
		coordinator = FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)
		coordinator.client = mock_client

		data = await coordinator._async_update_data()

		assert "children" in data
		assert "usage" in data
		assert "restrictions" in data
		assert len(data["children"]) == 2

	async def test_all_children_fetched_in_parallel(
		self, mock_config_entry: MagicMock, mock_client: AsyncMock
	) -> None:
		"""async_get_apps_and_usage must be called once per child."""
		hass = MagicMock()
		hass.data = {}
		coordinator = FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)
		coordinator.client = mock_client

		await coordinator._async_update_data()

		assert mock_client.async_get_apps_and_usage.call_count == len(MOCK_CHILDREN)

	async def test_failed_child_fetch_does_not_abort_others(
		self, mock_config_entry: MagicMock, mock_client: AsyncMock
	) -> None:
		"""If one child's fetch fails, the others should still succeed."""
		from custom_components.familylink.exceptions import NetworkError

		calls = 0

		async def _flaky(child_id: str) -> dict[str, Any]:
			nonlocal calls
			calls += 1
			if child_id == CHILD_ID_1:
				raise NetworkError("simulated failure")
			return make_raw_apps_and_usage(child_id)

		mock_client.async_get_apps_and_usage = _flaky
		hass = MagicMock()
		hass.data = {}
		coordinator = FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)
		coordinator.client = mock_client

		data = await coordinator._async_update_data()

		# The coordinator should still return data for the successful child
		assert CHILD_ID_2 in data["usage"]
		assert data["usage"][CHILD_ID_1] == []

	async def test_options_update_interval_respected(
		self, mock_config_entry: MagicMock
	) -> None:
		"""Coordinator should use options.update_interval over data.update_interval."""
		mock_config_entry.options = {"update_interval": 120}
		mock_config_entry.data = {"update_interval": 60}
		hass = MagicMock()
		coordinator = FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)
		assert coordinator.update_interval.seconds == 120

	async def test_get_members_uses_cache(
		self, mock_config_entry: MagicMock, mock_client: AsyncMock
	) -> None:
		"""async_get_members should return coordinator.data if already populated."""
		hass = MagicMock()
		coordinator = FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)
		coordinator.client = mock_client
		# Manually set cached data
		coordinator.data = {"children": MOCK_CHILDREN, "usage": {}, "restrictions": {}}

		result = await coordinator.async_get_members()

		assert result == MOCK_CHILDREN
		# Should NOT hit the API since cache is warm
		mock_client.async_get_members.assert_not_called()
