from sqlalchemy import select
from models.shipping_partner import ShipmentPartner
from fastapi import HTTPException, status


class ShippingPartnerRepository:
    def __init__(self, db):
        self.db = db

    async def get_shipping_partner_by_name(self, name):
        result = await self.db.execute(
            select(ShipmentPartner).where(ShipmentPartner.name == name)
        )
        return result.scalar_one_or_none()


class ShippingPartnerBaseService:
    def __init__(self, db):
        self.db = db

    def repo(self):
        return ShippingPartnerRepository(self.db)

    async def get_shipping_partner_or_404(self, name):
        partner = await self.repo().get_shipping_partner_by_name(name)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipping partner not found",
            )
        return partner


class ShippingPartnerService(ShippingPartnerBaseService):
    def __init__(self, db):
        super().__init__(db)

    def repo(self):
        return ShippingPartnerRepository(self.db)

    async def get_shipping_partner_by_name(self, name):
        return await self.repo().get_shipping_partner_by_name(name)
