from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from typing import Optional, Annotated
from service.utility_service import UtilityService

router = APIRouter()

def get_utility_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return UtilityService(db)

@router.get("/list")
async def list_activity_logs(
    service: Annotated[UtilityService, Depends(get_utility_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    order_id: Annotated[Optional[str], Query()] = None,
):
    """List activity logs with pagination and optional order filter"""
    return await service.list_activity_logs(page=page, limit=limit, order_id=order_id)