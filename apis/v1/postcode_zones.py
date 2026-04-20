from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Optional
from deps import get_db
from schemas.postcode_zones import PostcodeZoneCreate, PostcodeZoneOut
from schemas.common import PaginatedResponse
from service.zone_service import ZoneService

router = APIRouter()


def get_zone_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ZoneService(db)


@router.post(
    "/create-postcode-zone",
    response_model=PostcodeZoneOut,
    responses={
        400: {"description": "Zone not found or mapping already exists"},
        500: {"description": "Database error"},
    },
)
async def create_postcode_zone(
    payload: PostcodeZoneCreate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Create a Postcode-Zone mapping"""
    return await service.create_postcode_zone(payload)


@router.get(
    "/get-postcode-zone/{postcode_zone_id}",
    response_model=PostcodeZoneOut,
    responses={404: {"description": "Postcode Zone mapping not found"}},
)
async def get_postcode_zone(
    postcode_zone_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Get a Postcode-Zone mapping by ID"""
    result = await service.db.execute(
        service.repo()._select_postcode_zone_by_id(postcode_zone_id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Postcode Zone mapping not found")
    return mapping


@router.get("/list-postcode-zones", response_model=PaginatedResponse[PostcodeZoneOut])
async def list_postcode_zones(
    service: Annotated[ZoneService, Depends(get_zone_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query()] = 25,
    search: Annotated[Optional[str], Query()] = None,
    sort_by: Annotated[str, Query()] = "created_at",
    sort_dir: Annotated[str, Query()] = "desc",
):
    """List Postcode-Zone mappings with pagination and search"""
    items, total, pages, res_limit = await service.list_postcode_zones(
        page, limit, search, sort_by, sort_dir
    )
    return {
        "page": page,
        "limit": res_limit,
        "total": total,
        "pages": pages,
        "data": items,
    }


@router.delete(
    "/delete-postcode-zone/{postcode_zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Postcode Zone mapping not found"}},
)
async def delete_postcode_zone(
    postcode_zone_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Delete a Postcode-Zone mapping"""
    await service.delete_postcode_zone(postcode_zone_id)


@router.delete("/delete-all-postcode-zones", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_postcode_zones(
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Delete all Postcode-Zone mappings"""
    await service.delete_all_postcode_zones()
