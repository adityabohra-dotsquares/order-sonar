from fastapi import APIRouter, Depends, status
from typing import Annotated, List
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.shipping_partners import (
    ShipmentPartnerCreate,
    ShipmentPartnerUpdate,
    ShipmentPartnerResponse,
)
from service.shipment_admin_service import ShipmentAdminService

router = APIRouter()


def get_shipment_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ShipmentAdminService(db)


@router.post(
    "/create-shipping",
    response_model=ShipmentPartnerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_partner(
    partner: ShipmentPartnerCreate,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Create a new Shipment Partner"""
    return await service.create_partner(partner)


@router.get("/list-shipping", response_model=List[ShipmentPartnerResponse])
async def list_partners(
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """List all Shipment Partners"""
    return await service.list_partners()


@router.get(
    "/get-shipping/{partner_id}",
    response_model=ShipmentPartnerResponse,
    responses={404: {"description": "Shipment Partner not found"}},
)
async def get_partner(
    partner_id: str,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Get a Shipment Partner by ID"""
    return await service.get_partner(partner_id)


@router.put(
    "/update-shipping/{partner_id}",
    response_model=ShipmentPartnerResponse,
    responses={404: {"description": "Shipment Partner not found"}},
)
async def update_partner(
    partner_id: str,
    partner_update: ShipmentPartnerUpdate,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Update a Shipment Partner"""
    return await service.update_partner(partner_id, partner_update)


@router.delete(
    "/delete-shipping/{partner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Shipment Partner not found"}},
)
async def delete_partner(
    partner_id: str,
    service: Annotated[ShipmentAdminService, Depends(get_shipment_service)],
):
    """Delete a Shipment Partner"""
    await service.delete_partner(partner_id)
