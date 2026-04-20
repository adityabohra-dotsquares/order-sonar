from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ReturnReasonBase(BaseModel):
    reason: str
    is_active: bool = True

class ReturnReasonCreate(ReturnReasonBase):
    pass

class ReturnReasonUpdate(BaseModel):
    reason: Optional[str] = None
    is_active: Optional[bool] = None

class ReturnReasonOut(ReturnReasonBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
