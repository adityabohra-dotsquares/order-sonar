from fastapi import APIRouter, Depends, status, Query
from typing import List, Optional, Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.return_reasons import (
    ReturnReasonCreate,
    ReturnReasonUpdate,
    ReturnReasonOut,
)
from service.return_service import ReturnAdminService

router = APIRouter(tags=["Return Reasons"])

def get_return_admin_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ReturnAdminService(db)

@router.get("/", response_model=List[ReturnReasonOut])
async def list_return_reasons(
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
    is_active: Annotated[
        Optional[bool], Query(description="Filter by active status")
    ] = None,
):
    """List all return reasons with optional activity filter."""
    return await service.list_return_reasons(is_active=is_active)

@router.get("/active", response_model=List[ReturnReasonOut])
async def list_active_return_reasons(
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
):
    """List all active return reasons."""
    return await service.list_return_reasons(is_active=True)

@router.get(
    "/{reason_id}",
    response_model=ReturnReasonOut,
    responses={404: {"description": "Return reason not found"}},
)
async def get_return_reason(
    reason_id: str,
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
):
    """Fetch a specific return reason by ID."""
    return await service.get_return_reason(reason_id)

@router.post("/", response_model=ReturnReasonOut, status_code=status.HTTP_201_CREATED)
async def create_return_reason(
    reason_in: ReturnReasonCreate,
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
):
    """Create a new return reason."""
    return await service.create_return_reason(reason_in)

@router.patch(
    "/{reason_id}",
    response_model=ReturnReasonOut,
    responses={404: {"description": "Return reason not found"}},
)
async def update_return_reason(
    reason_id: str,
    reason_in: ReturnReasonUpdate,
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
):
    """Update an existing return reason."""
    return await service.update_return_reason(reason_id, reason_in)

@router.delete(
    "/{reason_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Return reason not found"}},
)
async def delete_return_reason(
    reason_id: str,
    service: Annotated[ReturnAdminService, Depends(get_return_admin_service)],
):
    """Delete a return reason."""
    await service.delete_return_reason(reason_id)
    return None
