"""Tools for the home appliance detector agent."""

from google.adk.tools.tool_context import ToolContext


def log_appliance(
    appliance_type: str,
    make: str,
    model: str,
    location: str,
    finish: str,
    tool_context: ToolContext,
    notes: str = "",
    user_id: str = "default_user"
) -> dict:
    """Logs a confirmed home appliance to the user's inventory.

    Args:
        appliance_type: The type of appliance (e.g., refrigerator, oven, dishwasher).
        make: The manufacturer/brand of the appliance (e.g., Samsung, GE, Bosch).
        model: The model number or name of the appliance (e.g., "RF28R7351SR", "LFXS30796D").
        location: Where in the home the appliance is located (e.g., kitchen, laundry room).
        finish: The finish/color of the appliance (e.g., "stainless steel", "black", "white").
        notes: Optional additional notes about the appliance.
        user_id: Optional user identifier (defaults to "default_user")
    """
    inventory = tool_context.state.get("appliance_inventory", [])

    entry = {
        "appliance_type": appliance_type,
        "make": make,
        "model": model,
        "location": location,
        "finish": finish,
        "notes": notes,
        "user_id": user_id
    }
    inventory.append(entry)
    tool_context.state["appliance_inventory"] = inventory

    return {
        "status": "success",
        "message": f"Logged {make} {model} {appliance_type} in {location} for user {user_id}",
        "total_appliances": len(inventory),
    }
