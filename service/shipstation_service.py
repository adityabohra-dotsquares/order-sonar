# app/services/shipstation_service.py
import httpx
import base64
from typing import Dict, Any, List
from models.orders import Order, OrderDetails
from datetime import datetime


class ShipStationService:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://ssapi.shipstation.com"

    def _get_auth_header(self) -> Dict[str, str]:
        # CORRECT WAY: API Key + API Secret (not username/password)
        credentials = f"{self.api_key}:{self.api_secret}"
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "utf-8"
        )

        return {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json",
        }

    async def get_shipping_rates(
        self, rate_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get shipping rates from multiple carriers"""
        url = f"{self.base_url}/shipments/getrates"
        headers = self._get_auth_header()

        try:
            response = requests.post(url, json=rate_data, headers=headers, timeout=30)

            if response.status_code == 400:
                # Parse the error details
                error_data = response.json()
                raise Exception(f"ShipStation validation error: {error_data}")

            response.raise_for_status()
            result = response.json()
            return result

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error contacting ShipStation: {str(e)}")

    async def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create an order in ShipStation"""
        try:
            url = f"{self.base_url}/orders/createorder"
            headers = self._get_auth_header()

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json=order_data, headers=headers, timeout=30.0
                )

            if response.status_code == 400:
                error_detail = response.json()
                raise Exception(f"ShipStation validation error: {error_detail}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"ShipStation API Error: {str(e)}")
            if hasattr(e, "response") and e.response is not None:
                print(f"Error response: {e.response.text}")
            raise Exception(f"Failed to create ShipStation order: {str(e)}")

    async def get_carriers(self) -> List[Dict[str, Any]]:
        """Get available carriers"""
        url = f"{self.base_url}/carriers"
        headers = self._get_auth_header()

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()

    async def create_shipment(
        self, order_id: str, shipment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a shipment for an order"""
        url = f"{self.base_url}/orders/createlabelfororder"
        headers = self._get_auth_header()

        data = {"orderId": order_id, **shipment_data}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()

    async def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get order details"""
        url = f"{self.base_url}/orders/{order_id}"
        headers = self._get_auth_header()

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        return response.json()

    async def delete_order(self, order_id: int) -> Dict[str, Any]:
        """Delete an order in ShipStation"""
        try:
            url = f"{self.base_url}/orders/{order_id}"
            headers = self._get_auth_header()

            async with httpx.AsyncClient() as client:
                response = await client.delete(url, headers=headers, timeout=30.0)

            if response.status_code == 400:
                error_detail = response.json()
                raise Exception(f"ShipStation validation error: {error_detail}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"ShipStation API Error: {str(e)}")
            if hasattr(e, "response") and e.response is not None:
                print(f"Error response: {e.response.text}")
            raise Exception(f"Failed to delete ShipStation order: {str(e)}")


async def convert_to_shipstation_format(
    order: Order, order_details: OrderDetails, order_data: dict
) -> dict:
    """Convert your internal order format to ShipStation format"""

    # Convert items to ShipStation format
    items = []
    for item in order_data.get("items", []):
        shipstation_item = {
            "sku": item.get("sku", ""),
            "name": item.get("name", ""),
            "quantity": item.get("quantity", 1),
            "unitPrice": float(item.get("price", 0)),
        }

        # Add weight if available
        if item.get("weight"):
            shipstation_item["weight"] = {
                "value": item["weight"],
                "units": "ounces",  # Convert to ounces for ShipStation
            }

        items.append(shipstation_item)

    # Prepare addresses
    shipstation_order = {
        "orderNumber": order.order_number,
        "orderDate": (
            order.created_at.isoformat()
            if order.created_at
            else datetime.utcnow().isoformat()
        ),
        "orderStatus": "awaiting_shipment",
        "customerUsername": order_details.customer_email,
        "customerEmail": order_details.customer_email,
        # Billing Address
        "billTo": {
            "name": f"{order_details.billing_first_name} {order_details.billing_last_name}".strip(),
            "company": order_details.billing_company,
            "street1": order_details.billing_address,
            "street2": order_details.billing_apartment,
            "city": order_details.billing_city,
            "state": order_details.billing_state,
            "postalCode": order_details.billing_postal_code,
            # "country": order_details.billing_country,
            "country": "US",
            "phone": order_details.billing_phone,
        },
        # Shipping Address
        "shipTo": {
            "name": f"{order_details.shipping_first_name} {order_details.shipping_last_name}".strip(),
            "company": order_details.shipping_company,
            "street1": order_details.shipping_address,
            "street2": order_details.shipping_apartment,
            "city": order_details.shipping_city,
            "state": order_details.shipping_state,
            "postalCode": order_details.shipping_postal_code,
            # "country": order_details.shipping_country,
            "country": "US",
            "phone": order_details.shipping_phone,
        },
        "items": items,
        "amountPaid": float(order.total_amount),
        "taxAmount": float(order.tax_amount),
        "shippingAmount": float(order.shipping_cost),
        "paymentMethod": "Credit Card",  # You can map this from your payment method
        "customerNotes": order.notes,
    }

    # Add gift message if applicable
    if order.is_gift and order.gift_message:
        shipstation_order["giftMessage"] = order.gift_message

    return shipstation_order


class ShipStationServiceV2:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.shipstation.com/v2"

    def _get_auth_header(self) -> Dict[str, str]:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def get_carriers(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/carriers"
        headers = self._get_auth_header()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data.get("carriers", []) if isinstance(data, dict) else data
        except Exception as e:
            raise Exception(f"Failed to fetch carriers from ShipStation V2: {str(e)}")

    async def get_services(self, carrier_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/carriers/{carrier_id}/services"
        headers = self._get_auth_header()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data.get("services", []) if isinstance(data, dict) else data
        except Exception as e:
            raise Exception(f"Failed to fetch services for carrier {carrier_id} from ShipStation V2: {str(e)}")





class ShipStationServiceV2:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://ssapi.shipstation.com"

    def _get_auth_header(self) -> Dict[str, str]:
        """Get authentication header for ShipStation API"""
        credentials = f"{self.api_key}:{self.api_secret}"
        encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode(
            "utf-8"
        )

        return {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json",
        }

    async def get_shipping_rates(
        self, rate_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get shipping rates from multiple carriers"""
        url = f"{self.base_url}/shipments/getrates"
        headers = self._get_auth_header()

        try:
            response = requests.post(url, json=rate_data, headers=headers, timeout=30)

            if response.status_code == 400:
                # Parse the error details
                error_data = response.json()
                raise Exception(f"ShipStation validation error: {error_data}")

            response.raise_for_status()
            result = response.json()
            return result

        except requests.exceptions.RequestException as e:
            raise Exception(f"Error contacting ShipStation: {str(e)}")

class ShipStationTrackingService:
    def __init__(self, api_key: str):
        self.base_url = "https://api.shipstation.com/v2"
        self.api_key = api_key

    def _get_headers(self):
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def track_shipment(self, tracking_number: str, carrier_code: str):
        url = f"{self.base_url}/tracking"
        params = {
            "tracking_number": tracking_number,
            "carrier_code": carrier_code,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            return response.json()