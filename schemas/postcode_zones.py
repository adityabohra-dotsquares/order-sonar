from pydantic import BaseModel
from datetime import datetime
from typing import Optional


from schemas.delivery_zones import DeliveryZoneOut

class PostcodeZoneBase(BaseModel):
    postcode: str
    zone_code: str


class PostcodeZoneCreate(BaseModel):
    postcode: str
    zone_code: str


class PostcodeZoneOut(BaseModel):
    id: str
    created_at: datetime
    postcode: str
    zone_id: str
    updated_at: datetime
    added_by: Optional[str] = None
    updated_by: Optional[str] = None
    zone: Optional[DeliveryZoneOut] = None

    class Config:
        from_attributes = True
