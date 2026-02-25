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
