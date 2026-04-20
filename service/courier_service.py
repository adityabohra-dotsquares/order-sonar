from typing import List
from sqlalchemy import select
from models.shipping_partner import ShipmentPartner
from schemas.shipping_partners import ShipmentPartnerCreate, ShipmentPartnerUpdate
from service.order_base_service import OrderBaseService
import uuid

class CourierService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)

    async def list_couriers(self, active_only: bool = False) -> List[ShipmentPartner]:
        """List all couriers, optionally filtering by active status"""
        stmt = select(ShipmentPartner)
        if active_only:
            stmt = stmt.where(ShipmentPartner.is_active == True)
        
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_courier(self, courier_id: str) -> ShipmentPartner:
        """Get a courier by ID or raise 404"""
        result = await self.db.execute(
            select(ShipmentPartner).where(ShipmentPartner.id == courier_id)
        )
        courier = result.scalar_one_or_none()
        if not courier:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Courier not found")
        return courier

    async def create_courier(self, payload: ShipmentPartnerCreate) -> ShipmentPartner:
        """Create a new courier"""
        # Check if name already exists
        result = await self.db.execute(
            select(ShipmentPartner).where(ShipmentPartner.name == payload.name)
        )
        if result.scalars().first():
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400, detail="Courier with this name already exists"
            )

        new_courier = ShipmentPartner(id=str(uuid.uuid4()), **payload.model_dump())
        self.db.add(new_courier)
        await self.db.commit()
        await self.db.refresh(new_courier)
        return new_courier

    async def update_courier(
        self, courier_id: str, payload: ShipmentPartnerUpdate
    ) -> ShipmentPartner:
        """Update an existing courier"""
        courier = await self.get_courier(courier_id)
        
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(courier, key, value)

        await self.db.commit()
        await self.db.refresh(courier)
        return courier

    async def delete_courier(self, courier_id: str) -> None:
        """Delete a courier"""
        courier = await self.get_courier(courier_id)
        await self.db.delete(courier)
        await self.db.commit()
