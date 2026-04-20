from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class ShipmentPartnerBase(BaseModel):
    name: str
    logo_url: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    tracking_url: Optional[str] = None
    is_active: Optional[bool] = True

    # Carrier Details
    code: Optional[str] = None
    account_number: Optional[str] = None
    requires_funded_account: Optional[bool] = False
    balance: Optional[float] = None
    nickname: Optional[str] = None
    shipping_provider_id: Optional[int] = None
    is_primary: Optional[bool] = False


class ShipmentPartnerCreate(ShipmentPartnerBase):
    added_by: Optional[str] = None


class ShipmentPartnerUpdate(BaseModel):
    name: Optional[str] = None
    logo_url: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    tracking_url: Optional[str] = None
    is_active: Optional[bool] = None
    updated_by: Optional[str] = None


class ShipmentPartnerResponse(ShipmentPartnerBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    added_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True
