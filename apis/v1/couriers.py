from typing import Annotated, List
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.shipping_partners import (
    ShipmentPartnerCreate,
    ShipmentPartnerUpdate,
    ShipmentPartnerResponse,
)
from deps import get_db
from service.courier_service import CourierService

router = APIRouter()

def get_courier_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return CourierService(db)

@router.get("/list-active-couriers", response_model=List[ShipmentPartnerResponse])
async def list_active_couriers(
    service: Annotated[CourierService, Depends(get_courier_service)]
):
    """List all Active Couriers"""
    return await service.list_couriers(active_only=True)

@router.get("/", response_model=List[ShipmentPartnerResponse])
async def list_all_couriers(
    service: Annotated[CourierService, Depends(get_courier_service)]
):
    """List all Couriers"""
    return await service.list_couriers()

@router.post(
    "/",
    response_model=ShipmentPartnerResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Courier with this name already exists"}},
)
async def create_courier(
    payload: ShipmentPartnerCreate,
    service: Annotated[CourierService, Depends(get_courier_service)],
):
    """Create a new Courier"""
    return await service.create_courier(payload)

@router.get(
    "/{courier_id}",
    response_model=ShipmentPartnerResponse,
    responses={404: {"description": "Courier not found"}},
)
async def get_courier(
    courier_id: str,
    service: Annotated[CourierService, Depends(get_courier_service)],
):
    """Get a Courier by ID"""
    return await service.get_courier(courier_id)

@router.patch(
    "/{courier_id}",
    response_model=ShipmentPartnerResponse,
    responses={404: {"description": "Courier not found"}},
)
async def update_courier(
    courier_id: str,
    payload: ShipmentPartnerUpdate,
    service: Annotated[CourierService, Depends(get_courier_service)],
):
    """Update a Courier"""
    return await service.update_courier(courier_id, payload)

@router.delete(
    "/{courier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Courier not found"}},
)
async def delete_courier(
    courier_id: str,
    service: Annotated[CourierService, Depends(get_courier_service)],
):
    """Delete a Courier"""
    await service.delete_courier(courier_id)
    return None

