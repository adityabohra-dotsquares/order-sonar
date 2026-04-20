from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from database import Base
import uuid

class ReturnReason(Base):
    __tablename__ = "return_reasons"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reason = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
