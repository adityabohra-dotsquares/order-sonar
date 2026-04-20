from pydantic import BaseModel
from typing import Optional, List, Dict, Literal
from datetime import datetime


class ShippingRuleCreate(BaseModel):
    seller_id: Optional[str] = None
    rule_type: str
    min_weight: Optional[float] = None
    max_weight: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    zone: Optional[str] = None
    pincode: Optional[str] = None
    category: Optional[str] = None
    carrier: Optional[str] = None
    base_cost: float = 0.0
    additional_cost_per_kg: Optional[float] = 0.0
    cod_available: bool = True
    free_shipping: bool = False
    priority: int = 10
    is_active: bool = True


class ShippingRuleOut(ShippingRuleCreate):
    id: str

    class Config:
        from_attributes = True


class ShippingZoneCreate(BaseModel):
    name: str
    states: Optional[List[str]] = []
    pincodes: Optional[List[str]] = []


class ShippingZoneOut(ShippingZoneCreate):
    id: str

    class Config:
        from_attributes = True


class CarrierRateCreate(BaseModel):
    carrier: str
    zone: str
    min_weight: float = 0.0
    max_weight: float = 999999.0
    cost: float = 0.0
    delivery_days: int = 3


class CarrierRateOut(CarrierRateCreate):
    id: str

    class Config:
        from_attributes = True


class CalculateRequest(BaseModel):
    seller_id: Optional[str] = None
    weight: float
    dimensions: Optional[Dict[str, float]] = None  # L,W,H in cm
    price: float
    destination_pincode: str
    category: Optional[str] = None
    cod: Optional[bool] = False
    shipping_tag: Optional[str] = None


class CalculateResponse(BaseModel):
    shipping_cost: float
    carrier: Optional[str] = None
    delivery_days: Optional[int] = None
    rule_id: Optional[str] = None
    free_shipping_applied: bool
    cod_available: bool


class RateByZoneCreate(BaseModel):
    zone: str
    rate: str
    product_identifier: str
    is_active: bool = True


class RateByZoneResponse(BaseModel):
    id: str
    zone: str
    rate: str
    product_identifier: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    added_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True


class RateByZoneUpdate(BaseModel):
    zone: Optional[str] = None
    rate: Optional[str] = None
    product_identifier: Optional[str] = None
    is_active: Optional[bool] = None


class ShippingCalculationResponse(BaseModel):
    product_identifier: str
    postcode: str
    zone: str
    shipping_type: Literal["PAID", "FREE", "NOT_SHIPPABLE"]
    shipping_cost: Optional[float] = None
    message: str


class CartItem(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    quantity: int = 1


class CartShippingRequest(BaseModel):
    items: List[CartItem]
    postcode: str


class CartShippingResponse(BaseModel):
    total_shipping_cost: float
    items: List[ShippingCalculationResponse]

