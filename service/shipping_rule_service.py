from typing import List, Optional, Dict, Any
from sqlalchemy import select
from models.shipping_rules import ShippingRule, ShippingZone, CarrierRate, RateByZone, PostcodeZone
from schemas.shipping_rules import (
    ShippingRuleCreate, ShippingZoneCreate, CarrierRateCreate,
    CalculateRequest, ShippingCalculationResponse,
    CartShippingRequest, CartShippingResponse
)
from service.order_base_service import OrderBaseService
from fastapi import HTTPException
import os

class ShippingRuleService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)
        self.PRICE_THRESHOLD = float(os.getenv("PRICE_THRESHOLD", 0))
        self.WEIGHT_RATE_PER_KG = float(os.getenv("WEIGHT_RATE_PER_KG", 0))
        self.BASE_SHIPPING_COST = float(os.getenv("SHIPPING_COST", 0))
        self.THRESHOLD_WEIGHT_VALUE = float(os.getenv("THRESHOLD_VALUE", 0))
        self.VOLUMETRIC_BASE = float(os.getenv("VOLUMETRIC_BASE", 5000))

    # --- Shipping Rules CRUD ---

    async def create_rule(self, payload: ShippingRuleCreate) -> ShippingRule:
        rule = ShippingRule(**payload.model_dump())
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def list_rules(self) -> List[ShippingRule]:
        res = await self.db.execute(
            select(ShippingRule).order_by(ShippingRule.created_at.desc())
        )
        return res.scalars().all()

    async def get_rule(self, rule_id: str) -> ShippingRule:
        res = await self.db.execute(select(ShippingRule).where(ShippingRule.id == rule_id))
        rule = res.scalars().first()
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        return rule

    async def update_rule(self, rule_id: str, payload: ShippingRuleCreate) -> ShippingRule:
        rule = await self.get_rule(rule_id)
        for k, v in payload.model_dump().items():
            setattr(rule, k, v)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def delete_rule(self, rule_id: str):
        rule = await self.get_rule(rule_id)
        await self.db.delete(rule)
        await self.db.commit()
        return {"detail": "deleted"}

    # --- Shipping Zones CRUD ---

    async def create_zone(self, payload: ShippingZoneCreate) -> ShippingZone:
        z = ShippingZone(**payload.model_dump())
        self.db.add(z)
        await self.db.commit()
        await self.db.refresh(z)
        return z

    async def list_zones(self) -> List[ShippingZone]:
        res = await self.db.execute(select(ShippingZone).order_by(ShippingZone.name.asc()))
        return res.scalars().all()

    # --- Carrier Rates CRUD ---

    async def create_carrier_rate(self, payload: CarrierRateCreate) -> CarrierRate:
        cr = CarrierRate(**payload.model_dump())
        self.db.add(cr)
        await self.db.commit()
        await self.db.refresh(cr)
        return cr

    async def list_carrier_rates(self) -> List[CarrierRate]:
        res = await self.db.execute(select(CarrierRate).order_by(CarrierRate.carrier.asc()))
        return res.scalars().all()

    # --- Calculation Logic ---

    def volumetric_weight(self, dimensions: Optional[Dict[str, float]]) -> float:
        if not dimensions:
            return 0.0
        L = dimensions.get("L") or dimensions.get("length") or 0.0
        W = dimensions.get("W") or dimensions.get("width") or 0.0
        H = dimensions.get("H") or dimensions.get("height") or 0.0
        return (L * W * H) / self.VOLUMETRIC_BASE

    async def calculate(self, payload: CalculateRequest) -> Dict[str, Any]:
        from service.orders import validate_pincode_from_file
        
        vol_w = self.volumetric_weight(payload.dimensions)
        chargeable_weight = max(payload.weight, vol_w)
        
        pincode_details = await validate_pincode_from_file(
            payload.destination_pincode, r"masters/AU_PINCODE_MASTER.txt"
        )
        if pincode_details is None:
            raise HTTPException(
                status_code=400, detail="Pincode not found. Please use a valid pincode."
            )
            
        shipping_cost = 0.0
        price = payload.price
        tag = payload.shipping_tag

        if tag == "free":
            shipping_cost = 0.0
        elif price >= self.PRICE_THRESHOLD:
            shipping_cost = 0.0
        elif chargeable_weight and chargeable_weight > self.THRESHOLD_WEIGHT_VALUE:
            shipping_cost = chargeable_weight * self.WEIGHT_RATE_PER_KG
        else:
            shipping_cost = self.BASE_SHIPPING_COST

        return {
            "shipping_cost": shipping_cost,
            "carrier": None,
            "delivery_days": None,
            "rule_id": None,
            "free_shipping_applied": False,
            "cod_available": False,
        }

    async def calculate_shipping(self, postcode: str, product_identifier: str) -> ShippingCalculationResponse:
        """Calculate shipping for a specific product and postcode based on RateByZone"""
        # 1. Find zone for postcode
        result = await self.db.execute(
            select(PostcodeZone.zone_id).where(PostcodeZone.postcode == postcode)
        )
        zone_id = result.scalar_one_or_none()

        if not zone_id:
            return ShippingCalculationResponse(
                product_identifier=product_identifier,
                postcode=postcode,
                zone="UNKNOWN",
                shipping_type="NOT_SHIPPABLE",
                message="Shipping is unavailable for this postcode.",
            )

        # 2. Fetch rate for product + zone
        result = await self.db.execute(
            select(RateByZone).where(
                RateByZone.product_identifier == product_identifier,
                RateByZone.zone_id == zone_id,
                RateByZone.is_active == True,
            )
        )
        rate_obj = result.scalar_one_or_none()

        if not rate_obj or not rate_obj.is_shipping_allowed or rate_obj.rate is None:
            return ShippingCalculationResponse(
                product_identifier=product_identifier,
                postcode=postcode,
                zone=zone_id,
                shipping_type="NOT_SHIPPABLE",
                message="This product cannot be shipped to your area.",
            )

        try:
            rate_val = float(rate_obj.rate)
        except (ValueError, TypeError):
            rate_val = 0.0

        if rate_val == 0:
            return ShippingCalculationResponse(
                product_identifier=product_identifier,
                postcode=postcode,
                zone=zone_id,
                shipping_type="FREE",
                shipping_cost=0,
                message="Free shipping available.",
            )

        return ShippingCalculationResponse(
            product_identifier=product_identifier,
            postcode=postcode,
            zone=zone_id,
            shipping_type="PAID",
            shipping_cost=rate_val,
            message="Shipping cost calculated successfully.",
        )

    async def calculate_cart_shipping(self, payload: CartShippingRequest) -> CartShippingResponse:
        total_cost = 0.0
        item_responses = []

        for item in payload.items:
            # Check variant first if provided, else product
            resp = await self._get_cart_item_rate(payload.postcode, item.product_id, item.variant_id)
            item_responses.append(resp)

            if resp.shipping_type == "PAID" and resp.shipping_cost:
                total_cost += resp.shipping_cost * item.quantity

        return CartShippingResponse(total_shipping_cost=total_cost, items=item_responses)

    async def _get_cart_item_rate(self, postcode: str, product_id: str, variant_id: Optional[str] = None) -> ShippingCalculationResponse:
        # Re-using calculate_shipping logic but with fallback from variant to product
        identifiers = [variant_id, product_id] if variant_id else [product_id]
        
        # 1. Find zone
        result = await self.db.execute(select(PostcodeZone.zone_id).where(PostcodeZone.postcode == postcode))
        zone_id = result.scalar_one_or_none()
        if not zone_id:
            return ShippingCalculationResponse(
                product_identifier=variant_id or product_id,
                postcode=postcode,
                zone="UNKNOWN",
                shipping_type="NOT_SHIPPABLE",
                message="Shipping is unavailable for this postcode.",
            )

        # 2. Try identifiers
        for identifier in identifiers:
            result = await self.db.execute(
                select(RateByZone).where(
                    RateByZone.product_identifier == identifier,
                    RateByZone.zone_id == zone_id,
                    RateByZone.is_active == True,
                )
            )
            rate_obj = result.scalar_one_or_none()
            if rate_obj:
                try:
                    rate_val = float(rate_obj.rate) if rate_obj.rate is not None else None
                except (ValueError, TypeError):
                    rate_val = None

                if not rate_obj.is_shipping_allowed or rate_val is None:
                    continue # Try next identifier

                return ShippingCalculationResponse(
                    product_identifier=identifier,
                    postcode=postcode,
                    zone=zone_id,
                    shipping_type="FREE" if rate_val == 0 else "PAID",
                    shipping_cost=rate_val,
                    message="Free shipping available." if rate_val == 0 else "Shipping cost calculated successfully."
                )

        return ShippingCalculationResponse(
            product_identifier=variant_id or product_id,
            postcode=postcode,
            zone=zone_id,
            shipping_type="NOT_SHIPPABLE",
            message="This product cannot be shipped to your area.",
        )
