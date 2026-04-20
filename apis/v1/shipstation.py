from fastapi import APIRouter, Depends
from typing import Dict, Any, Annotated
from schemas.shipstation import (
    ShipStationOrder,
    CarrierResponse,
    RateRequest,
    RateResponse,
    OrderRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from service.shipment_admin_service import ShipmentAdminService
from service.shipstation_service import ShipStationService
import os

router = APIRouter()

SHIPSTATION_API_KEY = os.getenv("SHIPSTATION_API_KEY")
SHIPSTATION_API_SECRET = os.getenv("SHIPSTATION_API_SECRET")

def get_shipstation_service():
    return ShipStationService(
        api_key=SHIPSTATION_API_KEY, api_secret=SHIPSTATION_API_SECRET
    )

def get_shipment_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ShipmentAdminService(db)

@router.post(
    "/get-rates",
    response_model=RateResponse,
    responses={400: {"description": "Failed to get shipping rates"}},
)
async def get_shipping_rates(
    rate_request: RateRequest,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get shipping rates from multiple carriers"""
    return await service.get_shipping_rates(rate_request)

@router.post(
    "/create-order",
    response_model=Dict[str, Any],
    responses={400: {"description": "Failed to create order"}},
)
async def create_shipstation_order(
    order: ShipStationOrder,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Create an order in ShipStation"""
    return await service.create_shipstation_order(order)

@router.post(
    "/get-order",
    response_model=Dict[str, Any],
    responses={400: {"description": "Failed to get order"}},
)
async def get_shipstation_order(
    order_request: OrderRequest,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get ShipStation order details"""
    return await service.get_shipstation_order(order_request.order_id)

@router.get(
    "/get-carriers",
    response_model=CarrierResponse,
    responses={400: {"description": "Failed to fetch carriers"}},
)
async def get_carriers(
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get available carriers and sync to DB"""
    carriers = await service.sync_carriers()
    return CarrierResponse(carriers=carriers)

@router.delete(
    "/delete-order",
    response_model=Dict[str, Any],
    responses={
        400: {"description": "Order already cancelled or failed to delete"},
        404: {"description": "Order not found in local database"},
    },
)
async def delete_shipstation_order(
    order_request: OrderRequest,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Delete an order in ShipStation and update status locally"""
    return await service.delete_shipstation_order(order_request)

@router.get(
    "/v2/get-carriers",
    response_model=CarrierResponse,
    responses={400: {"description": "Failed to fetch carriers V2"}},
)
async def get_carriers_v2(
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get available carriers using V2 API"""
    carriers = await service.list_carriers_v2()
    return CarrierResponse(carriers=carriers)

@router.get(
    "/v2/get-services/{carrier_id}",
    response_model=Dict[str, Any],
    responses={400: {"description": "Failed to fetch services V2"}},
)
async def get_services_v2(
    carrier_id: str,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get available services for a carrier using V2 API"""
    services = await service.get_services_v2(carrier_id)
    return {"carrier_id": carrier_id, "services": services}

@router.get(
    "/track-shipment",
    response_model=Dict[str, Any],
    responses={400: {"description": "Failed to track shipment"}},
)
async def track_shipment(
    tracking_number: str,
    carrier_code: str,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Track a shipment using ShipStation V2 API"""
    return await service.track_shipment(tracking_number, carrier_code)
