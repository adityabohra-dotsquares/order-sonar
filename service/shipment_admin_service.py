import os
import uuid
from typing import List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from models.shipping_partner import ShipmentPartner
from models.orders import Order, OrderStatus
from schemas.shipping_partners import ShipmentPartnerCreate, ShipmentPartnerUpdate
from schemas.shipstation import ShipStationOrder, RateRequest, OrderRequest
from service.order_base_service import OrderBaseService
from service.shipstation_service import ShipStationService, ShipStationServiceV2, ShipStationTrackingService
from utils.constants import messages

class ShipmentAdminService(OrderBaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.SHIPSTATION_API_KEY = os.getenv("SHIPSTATION_API_KEY")
        self.SHIPSTATION_API_SECRET = os.getenv("SHIPSTATION_API_SECRET")
        self.SHIPSTATION_API_KEY_V2 = os.getenv("SHIPSTATION_API_KEY_V2")

    def _get_shipstation_service(self):
        return ShipStationService(
            api_key=self.SHIPSTATION_API_KEY, api_secret=self.SHIPSTATION_API_SECRET
        )

    def _get_shipstation_service_v2(self):
        return ShipStationServiceV2(api_key=self.SHIPSTATION_API_KEY)

    # --- Shipment Partner CRUD ---

    async def create_partner(self, payload: ShipmentPartnerCreate) -> ShipmentPartner:
        result = await self.db.execute(
            select(ShipmentPartner).where(ShipmentPartner.name == payload.name)
        )
        if result.scalars().first():
            raise HTTPException(status_code=400, detail="Partner with this name already exists")
        
        partner = ShipmentPartner(id=str(uuid.uuid4()), **payload.model_dump())
        self.db.add(partner)
        await self.db.commit()
        await self.db.refresh(partner)
        return partner

    async def list_partners(self) -> List[ShipmentPartner]:
        result = await self.db.execute(select(ShipmentPartner))
        return list(result.scalars().all())

    async def get_partner(self, partner_id: str) -> ShipmentPartner:
        result = await self.db.execute(select(ShipmentPartner).where(ShipmentPartner.id == partner_id))
        partner = result.scalars().first()
        if not partner:
            raise HTTPException(status_code=404, detail=messages.get("shipping_partner_not_found"))
        return partner

    async def update_partner(self, partner_id: str, payload: ShipmentPartnerUpdate) -> ShipmentPartner:
        partner = await self.get_partner(partner_id)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(partner, k, v)
        await self.db.commit()
        await self.db.refresh(partner)
        return partner

    async def delete_partner(self, partner_id: str):
        partner = await self.get_partner(partner_id)
        await self.db.delete(partner)
        await self.db.commit()

    # --- ShipStation Operations ---

    async def get_shipping_rates(self, rate_request: RateRequest) -> Dict[str, Any]:
        service = self._get_shipstation_service()
        try:
            rates = await service.get_shipping_rates(rate_request.model_dump())
            return {"rates": rates}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get shipping rates: {str(e)}")

    async def create_shipstation_order(self, order: ShipStationOrder) -> Dict[str, Any]:
        service = self._get_shipstation_service()
        try:
            result = await service.create_order(order.model_dump())
            return {"success": True, "order": result}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to create ShipStation order: {str(e)}")

    async def get_shipstation_order(self, order_id: str) -> Dict[str, Any]:
        service = self._get_shipstation_service()
        try:
            order = await service.get_order(order_id)
            return {"success": True, "order": order}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to get ShipStation order: {str(e)}")

    async def sync_carriers(self) -> List[Dict[str, Any]]:
        service = self._get_shipstation_service()
        try:
            carriers = await service.get_carriers()
            for carrier in carriers:
                code = carrier.get("code")
                if not code: continue
                
                res = await self.db.execute(select(ShipmentPartner).where(ShipmentPartner.code == code))
                existing = res.scalar_one_or_none()
                
                data = {
                    "name": carrier.get("name"),
                    "account_number": carrier.get("accountNumber"),
                    "requires_funded_account": carrier.get("requiresFundedAccount", False),
                    "balance": carrier.get("balance"),
                    "nickname": carrier.get("nickname"),
                    "shipping_provider_id": carrier.get("shippingProviderId"),
                    "is_primary": carrier.get("primary", False),
                }
                
                if existing:
                    for k, v in data.items(): setattr(existing, k, v)
                else:
                    self.db.add(ShipmentPartner(id=str(uuid.uuid4()), code=code, is_active=True, **data))
                    
            await self.db.commit()
            return carriers
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to sync carriers: {str(e)}")

    async def delete_shipstation_order(self, order_request: OrderRequest) -> Dict[str, Any]:
        service = self._get_shipstation_service()
        
        result = await self.db.execute(select(Order).where(Order.id == order_request.order_id))
        order_model = result.scalar_one_or_none()
        if not order_model:
            raise HTTPException(status_code=404, detail="Order not found in local database")
        
        if order_model.shipstation_order_status == OrderStatus.CANCELLED:
            raise HTTPException(status_code=400, detail="Order is already cancelled")

        try:
            resp = await service.delete_order(order_model.shipstation_order_id)
            order_model.shipstation_order_status = OrderStatus.CANCELLED
            order_model.notes = order_request.cancel_message
            await self.db.commit()
            return {"success": True, "response": resp}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to delete order: {str(e)}")

    async def list_carriers_v2(self) -> List[Dict[str, Any]]:
        service = self._get_shipstation_service_v2()
        try:
            return await service.get_carriers()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch carriers V2: {str(e)}")

    async def get_services_v2(self, carrier_id: str) -> List[Dict[str, Any]]:
        service = self._get_shipstation_service_v2()
        try:
            return await service.get_services(carrier_id)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch services V2: {str(e)}")

    async def track_shipment(self, tracking_number: str, carrier_code: str) -> Dict[str, Any]:
        service = ShipStationTrackingService(api_key=self.SHIPSTATION_API_KEY_V2)
        try:
            result = await service.track_shipment(tracking_number, carrier_code)
            return {"success": True, "tracking_info": result}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to track shipment: {str(e)}")
