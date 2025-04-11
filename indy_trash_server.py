import logging
import os
from typing import Dict, Any, Optional

import requests
from modelcontextprotocol.server import McpServer, ToolContext, tool
from modelcontextprotocol.types.tool import ToolInputSchema, ToolParameter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Indy.gov API Configuration ---
SEARCH_GIS_ADDRESS_URL = "https://www.indy.gov/api/v1/search_gis_address"
PARCEL_URL = "https://www.indy.gov/api/v1/parcel"
TRASH_PICKUP_URL = "https://www.indy.gov/api/v1/indy_trash_pickup"
# This workflow ID seems static based on the example, might need verification
WORKFLOW_ID = "c2fdbada-0999-4a55-ad3e-8552b717c1da"

# --- Helper Functions for API Calls ---


def search_address(address_fragment: str) -> Optional[Dict[str, Any]]:
    """Calls the search_gis_address API."""
    try:
        response = requests.get(
            SEARCH_GIS_ADDRESS_URL,
            params={"address_fragment": address_fragment},
            timeout=10,
        )
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        data = response.json()
        if data.get("addresses") and len(data["addresses"]) == 1:
            # Assuming the first address is the correct one if unambiguous
            return data["addresses"][0]
        elif data.get("addresses") and len(data["addresses"]) > 1:
            logger.warning(f"Ambiguous address found for: {address_fragment}")
            # TODO: Handle ambiguous addresses - maybe return options or ask for clarification?
            # For now, return the first one as a best guess.
            return data["addresses"][0]
        else:
            logger.error(f"No address found for: {address_fragment}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling search_gis_address API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in search_address: {e}")
        return None


def get_parcel_info(address_details: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Calls the parcel API using details from the search_address result."""
    required_keys = ["address1", "city", "level", "number", "state", "tag", "zipcode"]
    if not all(key in address_details for key in required_keys):
        logger.error(
            f"Missing required keys in address_details for parcel API call: {address_details}"
        )
        return None

    params = {
        "address1": address_details["address1"],
        "city": address_details["city"],
        "level": address_details["level"],
        "number": address_details["number"],
        "state": address_details["state"],
        "tag_id": address_details[
            "tag"
        ],  # Note: API uses tag_id, search result provides tag
        "zipcode": address_details["zipcode"],
    }
    try:
        response = requests.get(PARCEL_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            # Assuming the first result is the correct parcel
            parcel_data = data[0]
            if "x" in parcel_data and "y" in parcel_data:
                return parcel_data
            else:
                logger.error(f"Parcel data missing x/y coordinates: {parcel_data}")
                return None
        else:
            logger.error(f"No parcel data found for details: {params}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling parcel API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_parcel_info: {e}")
        return None


def get_trash_pickup_details(parcel_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Calls the indy_trash_pickup API using coordinates from parcel info."""
    if "x" not in parcel_info or "y" not in parcel_info:
        logger.error(f"Missing x or y coordinates in parcel_info: {parcel_info}")
        return None

    params = {
        "__workflow_id": WORKFLOW_ID,
        "x": parcel_info["x"],
        "y": parcel_info["y"],
    }
    try:
        response = requests.get(TRASH_PICKUP_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and "pickup_day" in data:
            return data
        else:
            logger.error(f"Trash pickup data missing 'pickup_day': {data}")
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error calling trash pickup API: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_trash_pickup_details: {e}")
        return None


# --- MCP Tool Definition ---


@tool(
    name="get_indy_trash_day",
    description="Retrieves the trash pickup day for a given address in Indianapolis, IN.",
    input_schema=ToolInputSchema(
        parameters=[
            ToolParameter(
                name="address",
                description="The full street address (e.g., '123 Main St, Indianapolis, IN 46204').",
                type="string",
                required=True,
            )
        ]
    ),
)
async def get_indy_trash_day(ctx: ToolContext, address: str) -> str:
    """MCP Tool implementation to find the trash pickup day."""
    logger.info(f"Received request for address: {address}")

    # 1. Search/Validate Address
    address_details = search_address(address)
    if not address_details:
        return "Sorry, I couldn't validate that address. Please provide a valid Indianapolis address."
        # TODO: Potentially use ctx.request_user_input if the address was ambiguous?

    # 2. Get Parcel Info (for coordinates)
    parcel_info = get_parcel_info(address_details)
    if not parcel_info:
        return "Sorry, I couldn't retrieve parcel information for that address."

    # 3. Get Trash Pickup Details
    trash_details = get_trash_pickup_details(parcel_info)
    if not trash_details:
        return "Sorry, I couldn't retrieve trash pickup details for that address."

    # 4. Format and Return Result
    pickup_day = trash_details.get("pickup_day", "Not specified")
    heavy_trash = trash_details.get("heavy_trash_pickup", "")

    response = f"Your regular trash pickup day is {pickup_day}."
    if heavy_trash:
        response += f" Heavy trash pickup: {heavy_trash}."

    logger.info(f"Returning trash info for {address}: {response}")
    return response


# --- MCP Server Setup ---

# Create the server instance
# Pass environment variables for configuration if needed, e.g., host, port
mcp_server = McpServer(
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
    # Add other server configurations as needed (e.g., title, description)
)

# Register the tool(s)
mcp_server.register_tool(get_indy_trash_day)

# --- Main execution ---
# This part might vary slightly depending on how the MCP Python SDK expects to be run.
# Often, you'd use an ASGI server like uvicorn.
if __name__ == "__main__":
    import uvicorn

    # The MCP server object might expose an ASGI app directly, or you might need to wrap it.
    # Check the modelcontextprotocol Python SDK documentation for the exact way to run the server.
    # Assuming mcp_server acts like a FastAPI app or similar ASGI application:
    uvicorn.run(mcp_server.app, host=mcp_server.host, port=mcp_server.port)
    # If mcp_server has a run() method:
    # mcp_server.run()
