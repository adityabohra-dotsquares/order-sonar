from fastapi import APIRouter, Depends, Path, Body, Header, HTTPException, status
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.orders import OrderOut
from service.order_admin import OrderAdminService
import os

router = APIRouter()

SYSTEM_API_SECRET = os.getenv("SYSTEM_API_SECRET", "default_insecure_secret_change_me")


def verify_system_secret(
    x_system_secret: Annotated[str, Header(alias="X-System-Secret")] = None,
):
    if not x_system_secret or x_system_secret != SYSTEM_API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid system secret"
        )
    return True


def get_order_admin_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return OrderAdminService(db)


@router.patch(
    "/update-orders/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Invalid payment status or invalid state transition"},
        403: {"description": "Invalid system secret"},
        404: {"description": "Order not found"},
    },
    dependencies=[Depends(verify_system_secret)],
)
async def update_payment_status_system(
    order_id: Annotated[str, Path(title="The ID of the order to update")],
    payment_status: Annotated[str, Body(embed=True)],
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
):
    """
    System-only endpoint to update payment status.
    Protected by X-System-Secret header.
    """
    return await service.update_payment_status_system(order_id, payment_status)
