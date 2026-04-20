from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from admin_auth import require_superadmin
from service.order_admin import OrderAdminService

router = APIRouter()


def get_order_admin_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return OrderAdminService(db)


@router.delete(
    "/delete-all-orders",
    status_code=204,
    responses={500: {"description": "Failed to delete orders"}},
)
async def delete_all_orders(
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """
    Delete ALL orders.
    WARNING: This action is irreversible.
    """
    await service.delete_all_orders()
