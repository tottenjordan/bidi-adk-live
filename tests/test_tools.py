# tests/test_tools.py
"""Tests for the home agent tools."""

from unittest.mock import MagicMock

import pytest


class TestLogAppliance:
    """Tests for the log_appliance tool function."""

    def test_log_appliance_adds_to_empty_inventory(self):
        """First appliance creates the inventory list."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="refrigerator",
            make="Samsung",
            model="RF28R7351SR",
            location="kitchen",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        assert len(mock_context.state["appliance_inventory"]) == 1
        entry = mock_context.state["appliance_inventory"][0]
        assert entry["appliance_type"] == "refrigerator"
        assert entry["make"] == "Samsung"
        assert entry["model"] == "RF28R7351SR"
        assert entry["location"] == "kitchen"

    def test_log_appliance_appends_to_existing_inventory(self):
        """Subsequent appliances append to the list."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        existing = [{"appliance_type": "oven", "make": "GE", "model": "JB655", "location": "kitchen"}]
        mock_context.state = {"appliance_inventory": list(existing)}

        result = log_appliance(
            appliance_type="dishwasher",
            make="Bosch",
            model="SHPM88Z75N",
            location="kitchen",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        assert len(mock_context.state["appliance_inventory"]) == 2
        assert mock_context.state["appliance_inventory"][0]["appliance_type"] == "oven"
        assert mock_context.state["appliance_inventory"][1]["appliance_type"] == "dishwasher"

    def test_log_appliance_with_optional_notes(self):
        """Notes field is included when provided."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="washing machine",
            make="LG",
            model="WM4000HWA",
            location="laundry room",
            notes="Front loader, purchased 2024",
            tool_context=mock_context,
        )

        assert result["status"] == "success"
        entry = mock_context.state["appliance_inventory"][0]
        assert entry["notes"] == "Front loader, purchased 2024"

    def test_log_appliance_without_optional_notes(self):
        """Notes field defaults to empty string when not provided."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        mock_context.state = {}

        result = log_appliance(
            appliance_type="microwave",
            make="Panasonic",
            model="NN-SN66KB",
            location="kitchen",
            tool_context=mock_context,
        )

        entry = mock_context.state["appliance_inventory"][0]
        assert entry["notes"] == ""

    def test_log_appliance_returns_current_count(self):
        """Result includes the total inventory count."""
        from app.home_agent.tools import log_appliance

        mock_context = MagicMock()
        existing = [
            {"appliance_type": "oven", "make": "GE", "model": "JB655", "location": "kitchen"},
            {"appliance_type": "fridge", "make": "LG", "model": "LRMVS3006S", "location": "kitchen"},
        ]
        mock_context.state = {"appliance_inventory": list(existing)}

        result = log_appliance(
            appliance_type="dryer",
            make="Samsung",
            model="DVE45R6100W",
            location="laundry room",
            tool_context=mock_context,
        )

        assert result["total_appliances"] == 3
