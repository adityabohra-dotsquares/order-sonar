from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional
from deps import get_db
from schemas.rate_by_zones import RateByZoneCreate, RateByZoneUpdate, RateByZoneOut, ProductRateGroup
from schemas.common import PaginatedResponse
from service.zone_service import ZoneService

router = APIRouter()

def get_zone_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ZoneService(db)

@router.post(
    "/create-rate-by-zone",
    response_model=RateByZoneOut,
    responses={
        400: {"description": "Invalid SKU, zone code, or mapping already exists"},
        502: {"description": "Product service unavailable"},
    },
)
async def create_rate_by_zone(
    payload: RateByZoneCreate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Create a Rate By Zone mapping"""
    return await service.create_rate_by_zone(payload)

@router.get("/list-rates-by-zone", response_model=PaginatedResponse[RateByZoneOut])
async def list_rates_by_zone(
    service: Annotated[ZoneService, Depends(get_zone_service)],
    zone_code: Annotated[Optional[str], Query()] = None,
    product_identifier: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query()] = 25,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_dir: Annotated[str, Query()] = "desc",
):
    """List rates with caching and filters"""
    return await service.list_rates_by_zone(
        zone_code, product_identifier, page, limit, sort_by, sort_dir
    )

@router.get(
    "/get-rate-by-zone/{rate_id}",
    response_model=RateByZoneOut,
    responses={404: {"description": "Rate mapping not found"}},
)
async def get_rate_by_zone(
    rate_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Get a specific rate mapping"""
    result = await service.db.execute(
        service.repo()._select_rate_by_id(rate_id)
    )
    rate_obj = result.scalar_one_or_none()
    if not rate_obj:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Rate mapping not found")
    return rate_obj

@router.put(
    "/update-rate-by-zone/{rate_id}",
    response_model=RateByZoneOut,
    responses={404: {"description": "Rate mapping not found"}},
)
async def update_rate_by_zone(
    rate_id: str,
    payload: RateByZoneUpdate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Update an existing rate mapping"""
    return await service.update_rate_by_zone(rate_id, payload)

@router.delete(
    "/delete-rate-by-zone/{rate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Rate mapping not found"}},
)
async def delete_rate_by_zone(
    rate_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Delete a rate mapping"""
    await service.delete_rate_by_zone(rate_id)
    return

@router.delete("/delete-all-rates", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_rates(
    service: Annotated[ZoneService, Depends(get_zone_service)]
):
    """Delete all rate mappings"""
    await service.delete_all_rates()
    return

@router.get("/list-grouped-rates", response_model=PaginatedResponse[ProductRateGroup])
async def list_grouped_rates(
    service: Annotated[ZoneService, Depends(get_zone_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query()] = 25,
    search: Annotated[Optional[str], Query()] = None,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_dir: Annotated[str, Query()] = "desc",
):
    """List rates grouped by product with caching"""
    return await service.list_grouped_rates(page, limit, search, sort_by, sort_dir)

    