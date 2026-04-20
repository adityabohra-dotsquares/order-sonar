from sqlalchemy import select
from models.orders import Order
from fastapi import HTTPException, status
from service.utils import build_load_options


class OrderAdminRepository:
    def __init__(self, db):
        self.db = db

    async def get_order_by_id(
        self,
        order_id,
        includes: list = [],
        filters: list = [],
    ):
        stmt = (
            select(Order)
            .options(*build_load_options(Order, includes))
            .where(Order.id == order_id)
        )
        if filters:
            stmt = stmt.where(*filters)
        result = await self.db.execute(stmt)
        order = result.scalar_one_or_none()
        return order


class OrderBaseService:
    def __init__(self, db):
        self.db = db

    def repo(self):
        return OrderAdminRepository(self.db)

    async def get_order_or_404(self, order_id, filters=None, includes=None):
        order = await self.repo().get_order_by_id(
            order_id, includes=includes, filters=filters
        )
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
            )
        return order
