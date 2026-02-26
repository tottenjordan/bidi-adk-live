# BigQuery Appliance Logging Tool — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `executing-plans` skill to implement this plan task-by-task.

**Goal:** Add a second agent tool (`log_appliance_bq`) that writes appliance records to a BigQuery table AND session state in a single call, replacing `log_appliance` as the agent's primary tool.

**Architecture:** The new tool uses `google.cloud.bigquery.Client` to insert a row into `hybrid-vertex.appliances_v2.inventory` and also writes to `tool_context.state["appliance_inventory"]` (same as the existing tool). The agent prompt is updated to call `log_appliance_bq` instead of `log_appliance`. The existing `log_appliance` tool remains in the codebase but is no longer registered with the agent. BigQuery infrastructure (dataset + table) is created via a one-time `bq` CLI setup script.

**Tech Stack:** Python 3.12, google-cloud-bigquery (already installed as transitive dep), google-adk, pytest

---

## Task 1: Create BigQuery Dataset and Table

**Files:**
- Create: `scripts/create_bq_table.sh`

**Step 1: Write the setup script**

```bash
#!/usr/bin/env bash
# Creates the BigQuery dataset and table for appliance inventory.
# Requires: gcloud auth, GOOGLE_CLOUD_PROJECT set or passed as $1.
#
# Usage: ./scripts/create_bq_table.sh [project-id]

set -euo pipefail

PROJECT="${1:-hybrid-vertex}"
DATASET="appliances_v2"
TABLE="inventory"
LOCATION="us-central1"

echo "Creating dataset ${PROJECT}.${DATASET} ..."
bq --project_id="${PROJECT}" mk \
  --dataset \
  --location="${LOCATION}" \
  --description="Home appliance inventory (v2)" \
  "${DATASET}" 2>/dev/null || echo "Dataset already exists."

echo "Creating table ${PROJECT}.${DATASET}.${TABLE} ..."
bq --project_id="${PROJECT}" mk \
  --table \
  --description="Logged home appliances" \
  "${DATASET}.${TABLE}" \
  appliance_type:STRING,make:STRING,model:STRING,location:STRING,finish:STRING,notes:STRING,user_id:STRING,timestamp:TIMESTAMP \
  2>/dev/null || echo "Table already exists."

echo "Done. Table: ${PROJECT}.${DATASET}.${TABLE}"
bq --project_id="${PROJECT}" show --schema --format=prettyjson "${DATASET}.${TABLE}"
```

**Step 2: Run the script to create the infrastructure**

```bash
chmod +x scripts/create_bq_table.sh
./scripts/create_bq_table.sh hybrid-vertex
```

Expected: Dataset `appliances_v2` and table `inventory` created (or "already exists" if re-run).

**Step 3: Verify the table exists**

```bash
bq --project_id=hybrid-vertex show --schema --format=prettyjson appliances_v2.inventory
```

Expected: JSON schema output showing all 8 columns.

**Step 4: Commit**

```bash
git add scripts/create_bq_table.sh
git commit -m "infra: add BigQuery dataset/table setup script for appliance inventory"
```

---

## Task 2: Add `google-cloud-bigquery` as an Explicit Dependency

`google-cloud-bigquery` is currently available as a transitive dependency via `google-adk`, but since we're now importing it directly, it should be declared explicitly.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add the dependency**

In `pyproject.toml`, add `"google-cloud-bigquery>=3.20.0"` to the `dependencies` list:

```toml
dependencies = [
    "google-adk>=1.20.0",
    "fastapi>=0.115.0",
    "google-cloud-bigquery>=3.20.0",
    "python-dotenv>=1.0.0",
    "uvicorn[standard]>=0.32.0",
]
```

**Step 2: Sync dependencies**

```bash
uv sync --all-extras
```

Expected: Resolves without error (package already installed, just pinned now).

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add google-cloud-bigquery as explicit dependency"
```

---

## Task 3: Write Failing Tests for `log_appliance_bq`

**Files:**
- Create: `tests/test_tools_bq.py`

**Step 1: Write the test file**

These tests mock the BigQuery client so they run offline. They verify:
1. Session state is written (same as existing tool).
2. BigQuery `insert_rows_json` is called with the correct row.
3. Timestamp is added automatically.
4. BigQuery errors are surfaced in the return dict without crashing.
5. Optional `notes` defaults to empty string.

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_bq.py -v
```

Expected: All 7 tests FAIL with `ModuleNotFoundError: No module named 'app.home_agent.tools_bq'`.

**Step 3: Commit the failing tests**

```bash
git add tests/test_tools_bq.py
git commit -m "test: add failing tests for BigQuery log_appliance_bq tool"
```

---

## Task 4: Implement `log_appliance_bq`

**Files:**
- Create: `app/home_agent/tools_bq.py`

**Step 1: Write the implementation**

```python
"""BigQuery-backed tool for logging home appliances."""

import os
from datetime import datetime, timezone

from google.cloud import bigquery
from google.adk.tools.tool_context import ToolContext

# Lazy-init singleton — created on first tool call, reused thereafter.
_bq_client = None


def _get_bq_client() -> bigquery.Client:
    """Return a cached BigQuery client (created once per process)."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", "hybrid-vertex")
        )
    return _bq_client


# Fully-qualified table reference
_BQ_TABLE = "{project}.appliances_v2.inventory"


def log_appliance_bq(
    appliance_type: str,
    make: str,
    model: str,
    location: str,
    finish: str,
    tool_context: ToolContext,
    notes: str = "",
    user_id: str = "demo_user",
) -> dict:
    """Logs a confirmed home appliance to BigQuery and session state.

    Writes the appliance record to the BigQuery table
    `<project>.appliances_v2.inventory` for persistent storage,
    and also appends it to the session state inventory for in-session
    deduplication checks.

    Args:
        appliance_type: The type of appliance (e.g., refrigerator, oven, dishwasher).
        make: The manufacturer/brand of the appliance (e.g., Samsung, GE, Bosch).
        model: The model number or name of the appliance (e.g., "RF28R7351SR").
        location: Where in the home the appliance is located (e.g., kitchen, laundry room).
        finish: The finish/color of the appliance (e.g., "stainless steel", "black", "white").
        notes: Optional additional notes about the appliance.
        user_id: User identifier (defaults to "demo_user").
    """
    now = datetime.now(timezone.utc)

    # --- 1. Write to session state (always, even if BQ fails) ---
    inventory = tool_context.state.get("appliance_inventory", [])
    entry = {
        "appliance_type": appliance_type,
        "make": make,
        "model": model,
        "location": location,
        "finish": finish,
        "notes": notes,
        "user_id": user_id,
    }
    inventory.append(entry)
    tool_context.state["appliance_inventory"] = inventory

    # --- 2. Write to BigQuery ---
    row = {
        **entry,
        "timestamp": now.isoformat(),
    }

    client = _get_bq_client()
    project = client.project
    table_ref = _BQ_TABLE.format(project=project)
    errors = client.insert_rows_json(table_ref, [row])

    if errors:
        return {
            "status": "error",
            "message": f"Saved to session but BigQuery insert failed for {make} {model} {appliance_type}.",
            "bigquery_errors": errors,
            "total_appliances": len(inventory),
        }

    return {
        "status": "success",
        "message": f"Logged {make} {model} {appliance_type} in {location} for user {user_id}",
        "total_appliances": len(inventory),
    }
```

**Step 2: Run the tests**

```bash
uv run pytest tests/test_tools_bq.py -v
```

Expected: All 7 tests PASS.

**Step 3: Run the full test suite to confirm no regressions**

```bash
uv run pytest tests/ -v
```

Expected: All 25 tests PASS (18 existing + 7 new).

**Step 4: Commit**

```bash
git add app/home_agent/tools_bq.py
git commit -m "feat: add BigQuery-backed log_appliance_bq tool with dual-write"
```

---

## Task 5: Register New Tool with Agent and Update Prompt

**Files:**
- Modify: `app/home_agent/agent.py`

**Step 1: Update the agent to use `log_appliance_bq`**

Replace the import and tools registration. Keep `log_appliance` importable but don't register it with the agent. Update the one prompt line that references the tool name.

In `app/home_agent/agent.py`:

1. Change the import:
```python
from .tools_bq import log_appliance_bq
```

2. Change the `tools=` line:
```python
    tools=[log_appliance_bq],
```

3. In the instruction string, change:
```
AFTER capturing the FIVE details above, call the `log_appliance` tool.
```
to:
```
AFTER capturing the FIVE details above, call the `log_appliance_bq` tool.
```

**Step 2: Run agent tests to verify**

```bash
uv run pytest tests/test_agent.py -v
```

Expected: `test_agent_has_log_appliance_tool` will FAIL because it checks for `"log_appliance"` in tool names.

**Step 3: Update the agent test**

In `tests/test_agent.py`, update `test_agent_has_log_appliance_tool`:

```python
    def test_agent_has_log_appliance_tool(self):
        """Agent has the log_appliance_bq tool registered."""
        from app.home_agent import agent

        tool_names = [t.__name__ if callable(t) else str(t) for t in agent.tools]
        assert "log_appliance_bq" in tool_names
```

**Step 4: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All 25 tests PASS.

**Step 5: Commit**

```bash
git add app/home_agent/agent.py tests/test_agent.py
git commit -m "feat: register log_appliance_bq as the agent's primary tool"
```

---

## Task 6: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update the key files table**

Add a row for `tools_bq.py`:

```
| `app/home_agent/tools_bq.py` | `log_appliance_bq(...)` — dual-write to BigQuery (`appliances_v2.inventory`) and session state |
```

Update the `tools.py` row description to note it's the session-state-only version (kept but not registered with agent).

**Step 2: Update the session state section**

Add a note that the primary storage is now BigQuery, with session state used for in-session dedup.

**Step 3: Update the test count**

Change `18 total tests` to `25 total tests` and add a line for `test_tools_bq.py` (7 tests).

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for BigQuery tool addition"
```

---

## Task 7: End-to-End Smoke Test

**Step 1: Start the server**

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info
```

**Step 2: Connect via browser and log an appliance**

1. Open http://localhost:8000
2. Click Connect, enable Mic + Camera
3. Show an appliance, walk through the 5-step flow
4. After the agent calls `log_appliance_bq`, verify the confirmation message

**Step 3: Verify the BigQuery row**

```bash
bq --project_id=hybrid-vertex query --nouse_legacy_sql \
  "SELECT * FROM appliances_v2.inventory ORDER BY timestamp DESC LIMIT 5"
```

Expected: The appliance you just logged appears with all fields populated.

**Step 4: Verify session state still works**

In the browser debug panel, check the event console for the `function_response` — it should show `total_appliances` count incrementing.

---

## Summary of Changes

| File | Action | Purpose |
|------|--------|---------|
| `scripts/create_bq_table.sh` | Create | One-time BigQuery infra setup |
| `pyproject.toml` | Modify | Add `google-cloud-bigquery` explicit dep |
| `tests/test_tools_bq.py` | Create | 7 unit tests for the new tool |
| `app/home_agent/tools_bq.py` | Create | New tool: dual-write to BQ + session state |
| `app/home_agent/agent.py` | Modify | Register `log_appliance_bq`, update prompt |
| `tests/test_agent.py` | Modify | Update tool name assertion |
| `CLAUDE.md` | Modify | Document new tool, update test counts |
