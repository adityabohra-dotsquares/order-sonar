from fastapi import APIRouter, Depends, Query
from typing import Optional, Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.background_tasks import BackgroundTaskSchema, BackgroundTaskList
from service.utility_service import UtilityService

router = APIRouter()

def get_utility_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return UtilityService(db)

@router.get("", response_model=BackgroundTaskList)
async def list_background_tasks(
    service: Annotated[UtilityService, Depends(get_utility_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    task_type: Annotated[Optional[str], Query()] = None,
    status: Annotated[Optional[str], Query()] = None,
):
    """List all background tasks with pagination and optional filtering."""
    return await service.list_background_tasks(
        page=page, page_size=page_size, task_type=task_type, status=status
    )

@router.get(
    "/{task_id}",
    response_model=BackgroundTaskSchema,
    responses={404: {"description": "Task not found"}},
)
async def get_background_task_details(
    task_id: str,
    service: Annotated[UtilityService, Depends(get_utility_service)],
):
    """Fetch details of a specific background task."""
    return await service.get_background_task_details(task_id)
