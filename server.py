import logging
from typing import Dict, Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Indy.gov API Configuration ---
SEARCH_GIS_ADDRESS_URL = "https://www.indy.gov/api/v1/search_gis_address"
PARCEL_URL = "https://www.indy.gov/api/v1/parcel"
TRASH_PICKUP_URL = "https://www.indy.gov/api/v1/indy_trash_pickup"


mcp = FastMCP("Indy Trash Pickup Day")


async def search_address(address_fragment: str) -> Optional[Dict[str, Any]]:
    """Calls the search_gis_address API."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                SEARCH_GIS_ADDRESS_URL,
                params={"address_fragment": address_fragment},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("addresses") and len(data["addresses"]) == 1:
                return data["addresses"][0]
            elif data.get("addresses") and len(data["addresses"]) > 1:
                logger.warning(f"Ambiguous address found for: {address_fragment}")
                return data["addresses"][0]
            else:
                logger.error(f"No address found for: {address_fragment}")
                return None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                logger.warning("retrying without the street type")
                return await search_address(" ".join(address_fragment.split(" ")[:-1]))
            logger.error(f"HTTP error calling search_gis_address API: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Error calling search_gis_address API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in search_address: {e}")
            return None


async def get_parcel_info(address_details: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
        "tag_id": address_details["tag"],
        "zipcode": address_details["zipcode"],
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(PARCEL_URL, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                parcel_data = data[0]
                if "x" in parcel_data and "y" in parcel_data:
                    return parcel_data
                else:
                    logger.error(f"Parcel data missing x/y coordinates: {parcel_data}")
                    return None
            else:
                logger.error(f"No parcel data found for details: {params}")
                return None
        except httpx.RequestError as e:
            logger.error(f"Error calling parcel API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_parcel_info: {e}")
            return None


async def get_trash_pickup_details(
    parcel_info: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Calls the indy_trash_pickup API using coordinates from parcel info."""
    if "x" not in parcel_info or "y" not in parcel_info:
        logger.error(f"Missing x or y coordinates in parcel_info: {parcel_info}")
        return None

    params = {
        "x": parcel_info["x"],
        "y": parcel_info["y"],
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(TRASH_PICKUP_URL, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            if data and "pickup_day" in data:
                return data
            else:
                logger.error(f"Trash pickup data missing 'pickup_day': {data}")
                return None
        except httpx.RequestError as e:
            logger.error(f"Error calling trash pickup API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in get_trash_pickup_details: {e}")
            return None


@mcp.tool()
async def get_indy_trash_day(address: str) -> str:
    """Get the trash pickup day for an Indianapolis address.

    Args:
        address: Street number and name only (e.g. "1234 Main Street").
                Do not include city, state, or zip code.

    Returns:
        A string describing the trash pickup schedule.
    """

    logger.info(f"Received request for address: {address}")

    # 1. Search/Validate Address
    address_details = await search_address(address)
    if not address_details:
        return "Sorry, I couldn't validate that address. Please provide a valid Indianapolis address."

    # 2. Get Parcel Info (for coordinates)
    parcel_info = await get_parcel_info(address_details)
    if not parcel_info:
        return "Sorry, I couldn't retrieve parcel information for that address."

    # 3. Get Trash Pickup Details
    trash_details = await get_trash_pickup_details(parcel_info)
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
