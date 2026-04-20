from sqlalchemy import Column, String, DateTime, Boolean,Float,Integer
from sqlalchemy.sql import func
from database import Base
import uuid


class ShipmentPartner(Base):
    __tablename__ = "shipment_partners"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    name = Column(String(100), unique=True, nullable=False)
    logo_url = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(20), nullable=True)
    tracking_url = Column(String(255), nullable=True)
    is_active = Column(Boolean(), default=True)

    # Carrier Details (e.g. for ShipStation)
    code = Column(String(50), nullable=True)
    account_number = Column(String(100), nullable=True)
    requires_funded_account = Column(Boolean(), default=False)
    balance = Column(Float(), nullable=True)
    nickname = Column(String(100), nullable=True)
    shipping_provider_id = Column(Integer(), nullable=True)
    is_primary = Column(Boolean(), default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    added_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)

    # relationships
    # shipments = relationship("Shipment", back_populates="partner")
