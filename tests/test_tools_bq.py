# tests/test_tools_bq.py
"""Tests for the BigQuery-backed log_appliance_bq tool."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestLogApplianceBQ:
    """Tests for the log_appliance_bq tool function."""

    def _call_tool(self, mock_bq_client=None, **kwargs):
        """Helper to call log_appliance_bq with a mocked BQ client."""
        from app.home_agent.tools_bq import log_appliance_bq

        mock_context = MagicMock()
        mock_context.state = kwargs.pop("state", {})

        if mock_bq_client is None:
            mock_bq_client = MagicMock()
            mock_bq_client.insert_rows_json.return_value = []  # no errors

        with patch("app.home_agent.tools_bq._get_bq_client", return_value=mock_bq_client):
            result = log_appliance_bq(tool_context=mock_context, **kwargs)

        return result, mock_context, mock_bq_client

    def test_writes_to_session_state(self):
        """Tool writes appliance entry to session state like the original tool."""
        result, mock_context, _ = self._call_tool(
            appliance_type="refrigerator",
            make="Samsung",
            model="RF28R7351SR",
            location="kitchen",
            finish="stainless steel",
        )

        assert result["status"] == "success"
        inventory = mock_context.state["appliance_inventory"]
        assert len(inventory) == 1
        assert inventory[0]["appliance_type"] == "refrigerator"
        assert inventory[0]["make"] == "Samsung"
        assert inventory[0]["finish"] == "stainless steel"
        assert inventory[0]["user_id"] == "demo_user"

    def test_calls_bigquery_insert(self):
        """Tool calls BigQuery insert_rows_json with correct data."""
        mock_bq = MagicMock()
        mock_bq.insert_rows_json.return_value = []

        result, _, mock_bq = self._call_tool(
            mock_bq_client=mock_bq,
            appliance_type="oven",
            make="GE",
            model="JB655",
            location="kitchen",
            finish="black",
        )

        mock_bq.insert_rows_json.assert_called_once()
        call_args = mock_bq.insert_rows_json.call_args
        table_ref = call_args[0][0]
        rows = call_args[0][1]

        assert "appliances_v2.inventory" in table_ref
        assert len(rows) == 1
        assert rows[0]["appliance_type"] == "oven"
        assert rows[0]["make"] == "GE"
        assert rows[0]["model"] == "JB655"
        assert rows[0]["finish"] == "black"
        assert rows[0]["user_id"] == "demo_user"
        assert "timestamp" in rows[0]

    def test_timestamp_is_utc_iso(self):
        """Timestamp field is a valid UTC ISO-8601 string."""
        result, mock_context, mock_bq = self._call_tool(
            appliance_type="dishwasher",
            make="Bosch",
            model="SHPM88Z75N",
            location="kitchen",
            finish="white",
        )

        call_args = mock_bq.insert_rows_json.call_args
        row = call_args[0][1][0]
        ts = datetime.fromisoformat(row["timestamp"])
        assert ts.tzinfo is not None  # timezone-aware

    def test_bigquery_error_returns_error_status(self):
        """If BigQuery insert fails, result includes error but does not raise."""
        mock_bq = MagicMock()
        mock_bq.insert_rows_json.return_value = [{"index": 0, "errors": ["some error"]}]

        result, mock_context, _ = self._call_tool(
            mock_bq_client=mock_bq,
            appliance_type="microwave",
            make="Panasonic",
            model="NN-SN66KB",
            location="kitchen",
            finish="black",
        )

        assert result["status"] == "error"
        assert "bigquery_errors" in result
        # Session state should still be written even if BQ fails
        assert len(mock_context.state["appliance_inventory"]) == 1

    def test_optional_notes_default(self):
        """Notes defaults to empty string when not provided."""
        result, mock_context, mock_bq = self._call_tool(
            appliance_type="dryer",
            make="Samsung",
            model="DVE45R6100W",
            location="laundry room",
            finish="white",
        )

        row = mock_bq.insert_rows_json.call_args[0][1][0]
        assert row["notes"] == ""
        assert mock_context.state["appliance_inventory"][0]["notes"] == ""

    def test_custom_user_id(self):
        """User ID can be overridden from the default."""
        result, mock_context, mock_bq = self._call_tool(
            appliance_type="washer",
            make="LG",
            model="WM4000HWA",
            location="laundry room",
            finish="white",
            user_id="custom_user_123",
        )

        row = mock_bq.insert_rows_json.call_args[0][1][0]
        assert row["user_id"] == "custom_user_123"
        assert mock_context.state["appliance_inventory"][0]["user_id"] == "custom_user_123"

    def test_appends_to_existing_inventory(self):
        """New entries append to existing session state inventory."""
        existing = [{"appliance_type": "oven", "make": "GE", "model": "JB655", "location": "kitchen"}]

        result, mock_context, _ = self._call_tool(
            state={"appliance_inventory": list(existing)},
            appliance_type="fridge",
            make="LG",
            model="LRMVS3006S",
            location="kitchen",
            finish="stainless steel",
        )

        assert result["total_appliances"] == 2
        assert mock_context.state["appliance_inventory"][0]["appliance_type"] == "oven"
        assert mock_context.state["appliance_inventory"][1]["appliance_type"] == "fridge"
