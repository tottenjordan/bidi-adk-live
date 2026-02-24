"""Tools for the home appliance detector agent."""

from google.adk.tools.tool_context import ToolContext


def log_appliance(
    appliance_type: str,
    make: str,
    model: str,
    location: str,
    tool_context: ToolContext,
    notes: str = "",
) -> dict:
    """Logs a confirmed home appliance to the user's inventory.

    Args:
        appliance_type: The type of appliance (e.g., refrigerator, oven, dishwasher).
        make: The manufacturer/brand of the appliance (e.g., Samsung, GE, Bosch).
        model: The model number or name of the appliance.
        location: Where in the home the appliance is located (e.g., kitchen, laundry room).
        notes: Optional additional notes about the appliance.
    """
    inventory = tool_context.state.get("appliance_inventory", [])

    entry = {
        "appliance_type": appliance_type,
        "make": make,
        "model": model,
        "location": location,
        "notes": notes,
    }
    inventory.append(entry)
    tool_context.state["appliance_inventory"] = inventory

    return {
        "status": "success",
        "message": f"Logged {make} {model} {appliance_type} in {location}.",
        "total_appliances": len(inventory),
    }
