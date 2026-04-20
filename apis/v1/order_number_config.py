from fastapi import APIRouter, Depends
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.order_number_config import OrderNumberConfigOut, OrderNumberConfigUpdate
from service.config_service import ConfigService

router = APIRouter()

def get_config_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ConfigService(db)

@router.get(
    "",
    response_model=OrderNumberConfigOut,
    responses={404: {"description": "Order number configuration not initialized yet."}},
)
async def get_order_number_config(
    service: Annotated[ConfigService, Depends(get_config_service)]
):
    """Fetch the order number configuration."""
    return await service.get_order_number_config()

@router.patch("", response_model=OrderNumberConfigOut)
async def update_order_number_config(
    config_in: OrderNumberConfigUpdate,
    service: Annotated[ConfigService, Depends(get_config_service)],
):
    """Update or create the order number configuration."""
    return await service.update_order_number_config(config_in)
