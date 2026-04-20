from fastapi import APIRouter, Depends
from typing import Annotated
from service.aramex_service import AramexService

router = APIRouter()

def get_aramex_service():
    return AramexService()

@router.get("/track/{tracking_number}")
async def track_order(
    tracking_number: str,
    service: Annotated[AramexService, Depends(get_aramex_service)],
):
    """Track an order via Aramex"""
    return await service.get_tracking_details(tracking_number)

@router.get("/all-consignments")
async def track_all_orders(
    service: Annotated[AramexService, Depends(get_aramex_service)],
):
    """Fetch all consignments from Aramex"""
    return await service.get_all_consignments()