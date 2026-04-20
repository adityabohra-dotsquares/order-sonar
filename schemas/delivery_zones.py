from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class DeliveryZoneBase(BaseModel):
    zone_code: str
    zone_name: str
    is_active: bool = True


class DeliveryZoneCreate(DeliveryZoneBase):
    pass


class DeliveryZoneOut(DeliveryZoneBase):
    id: str
    created_at: datetime
    updated_at: datetime
    added_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True
