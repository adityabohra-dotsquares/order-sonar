from pydantic import BaseModel
from typing import Optional

class OrderNumberConfigBase(BaseModel):
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    is_active: bool = True

class OrderNumberConfigUpdate(BaseModel):
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    is_active: Optional[bool] = None

class OrderNumberConfigOut(OrderNumberConfigBase):
    id: int

    class Config:
        from_attributes = True
