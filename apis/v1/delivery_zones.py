from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional
from deps import get_db
from schemas.delivery_zones import DeliveryZoneCreate, DeliveryZoneOut
from schemas.common import PaginatedResponse
from service.zone_service import ZoneService

router = APIRouter()

def get_zone_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ZoneService(db)

@router.post(
    "/create-zone",
    response_model=DeliveryZoneOut,
    responses={400: {"description": "Delivery Zone already exists"}},
)
async def create_delivery_zone(
    payload: DeliveryZoneCreate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Create a Delivery Zone"""
    return await service.create_delivery_zone(payload)

@router.put(
    "/update-zone/{zone_id}",
    response_model=DeliveryZoneOut,
    responses={
        400: {"description": "Delivery Zone with this code and name already exists"},
        404: {"description": "Delivery Zone not found"},
    },
)
async def update_delivery_zone(
    zone_id: str,
    payload: DeliveryZoneCreate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Update a Delivery Zone by ID"""
    return await service.update_delivery_zone(zone_id, payload)

@router.get("/list-zones", response_model=PaginatedResponse[DeliveryZoneOut])
async def list_delivery_zones(
    service: Annotated[ZoneService, Depends(get_zone_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query()] = 25,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_dir: Annotated[str, Query()] = "desc",
    search: Annotated[Optional[str], Query()] = None,
):
    """List Delivery Zones with pagination and search"""
    items, total, pages, res_limit = await service.list_delivery_zones(
        page, limit, search, sort_by, sort_dir
    )
    return {
        "page": page,
        "limit": res_limit,
        "total": total,
        "pages": pages,
        "data": items,
    }

@router.get(
    "/get-zone/{zone_id}",
    response_model=DeliveryZoneOut,
    responses={404: {"description": "Delivery Zone not found"}},
)
async def get_delivery_zone(
    zone_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Get a Delivery Zone by ID"""
    return await service.get_delivery_zone(zone_id)

@router.delete(
    "/delete-zone/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "Delivery Zone not found"},
        500: {"description": "Delivery Zone is associated with other data"},
    },
)
async def delete_delivery_zone(
    zone_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Delete a Delivery Zone"""
    await service.delete_delivery_zone(zone_id)
    return None
