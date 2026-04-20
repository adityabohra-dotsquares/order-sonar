from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from schemas.delivery_zones import DeliveryZoneOut
from decimal import Decimal

class RateByZoneBase(BaseModel):
    product_identifier: str
    zone_code: str
    rate: Optional[Decimal] = None
    is_active: bool = True


class RateByZoneCreate(RateByZoneBase):
    pass


class RateByZoneUpdate(BaseModel):
    rate: Optional[Decimal] = None
    is_active: Optional[bool] = None


class RateByZoneOut(RateByZoneBase):
    id: str
    created_at: datetime
    updated_at: datetime
    added_by: Optional[str] = None
    updated_by: Optional[str] = None
    zone: Optional[DeliveryZoneOut] = None

    class Config:
        from_attributes = True

from typing import Dict, Any, Optional, List
class ProductRateGroup(BaseModel):
    product_identifier: str
    product_details: Optional[Dict[str, Any]] = None
    rates: List[RateByZoneOut]
