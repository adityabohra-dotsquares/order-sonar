import httpx
import os
from typing import List, Dict, Any, Optional
from loguru import logger
from datetime import datetime

class AramexError(Exception):
    """Base exception for Aramex Service"""
    pass

class AramexAuthError(AramexError):
    """Raised when authentication fails"""
    pass

class AramexApiError(AramexError):
    """Raised when API request fails"""
    pass

class AramexService:
    def __init__(self):
        self.client_id = os.getenv("ARAMEX_CLIENT_ID")
        self.client_secret = os.getenv("ARAMEX_CLIENT_SECRET")
        self.authority = os.getenv("ARAMEX_AUTHORITY", "https://identity.aramexconnect.com.au/connect/token")
        self.base_address = os.getenv("ARAMEX_BASE_ADDRESS", "https://api.aramexconnect.com.au")
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None

    async def get_access_token(self) -> str:
        """Fetch OAuth2 access token from Aramex Identity server"""
        # Simple caching check (can be improved with expiry parsing)
        if self.access_token:
             return self.access_token

        if not self.client_id or not self.client_secret:
            raise ValueError("ARAMEX_CLIENT_ID and ARAMEX_CLIENT_SECRET environment variables are required")

        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Fetching Aramex token from {self.authority}")
                response = await client.post(
                    self.authority,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        # Scope might be needed, but README didn't specify a required one for Track
                    },
                    timeout=10
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to fetch Aramex token: {response.status_code} - {response.text}")
                    raise AramexAuthError(f"Aramex Authentication failed: {response.text}")

                result = response.json()
                self.access_token = result.get("access_token")
                return self.access_token

            except httpx.RequestError as e:
                logger.error(f"Error connecting to Aramex Identity server: {str(e)}")
                raise AramexAuthError(f"Aramex Authentication error: {str(e)}")

    async def get_tracking_details(self, tracking_number: str) -> List[Dict[str, Any]]:
        """
        Fetch tracking details for a given label number (tracking number).
        Endpoint: {base_address}/api/track/{tracking_number}
        """
        token = await self.get_access_token()
        url = f"{self.base_address}/api/track/{tracking_number}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Fetching Aramex tracking for {tracking_number} from {url}")
                response = await client.get(url, headers=headers, timeout=15)

                if response.status_code == 404:
                     logger.warning(f"No tracking info found for {tracking_number}")
                     return []

                if response.status_code != 200:
                    logger.error(f"Aramex API Error: {response.status_code} - {response.text}")
                    raise AramexApiError(f"Aramex API Error: {response.text}")

                result = response.json()
                # Based on Wiki: { "data": [ { ... } ] }
                return result.get("data", [])

            except httpx.RequestError as e:
                logger.error(f"Error connecting to Aramex API: {str(e)}")
                raise AramexApiError(f"Aramex API connection error: {str(e)}")

    async def get_all_consignments(self):
        """
        Fetch all consignments from Aramex.
        Endpoint: {base_address}/api/consignments
        """
        token = await self.get_access_token()
        url = f"{self.base_address}/api/consignments"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Fetching all Aramex consignments from {url}")
                response = await client.get(url, headers=headers, timeout=15)

                if response.status_code != 200:
                    logger.error(f"Aramex API Error: {response.status_code} - {response.text}")
                    raise AramexApiError(f"Aramex API Error: {response.text}")

                result = response.json()
                # Based on Wiki: { "data": [ { ... } ] }
                return result.get("data", [])

            except httpx.RequestError as e:
                logger.error(f"Error connecting to Aramex API: {str(e)}")
                raise AramexApiError(f"Aramex API connection error: {str(e)}")