from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    func,
    JSON,
    Enum as SQLEnum,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from database import Base
import uuid

from sqlalchemy import Index

class ShippingRuleType:
    WEIGHT = "WEIGHT"
    PRICE = "PRICE"
    ZONE = "ZONE"
    PINCODE = "PINCODE"
    CATEGORY = "CATEGORY"
    CARRIER = "CARRIER"


class ShippingRule(Base):
    __tablename__ = "shipping_rules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seller_id = Column(String(36), nullable=True)

    rule_type = Column(
        SQLEnum(
            "WEIGHT", "PRICE", "ZONE", "PINCODE", "CATEGORY", "CARRIER",
            name="shipping_rule_types",
        ),
        nullable=False,
    )

    zone_id = Column(
        String(36),
        ForeignKey("delivery_zones.id"),
        nullable=True,
    )

    min_weight = Column(Float, nullable=True)
    max_weight = Column(Float, nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)

    pincode = Column(String(10), nullable=True)
    category = Column(String(50), nullable=True)
    carrier = Column(String(50), nullable=True)

    base_cost = Column(Float, nullable=False, default=0.0)
    additional_cost_per_kg = Column(Float, nullable=True, default=0.0)

    cod_available = Column(Boolean, default=True)
    free_shipping = Column(Boolean, default=False)

    priority = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())



class ShippingZone(Base):
    __tablename__ = "shipping_zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(50), nullable=False)
    # states and pincodes stored as arrays (JSON)
    states = Column(JSON, default=list)
    pincodes = Column(JSON, default=list)


class CarrierRate(Base):
    __tablename__ = "carrier_rates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    carrier = Column(String(50), nullable=False)
    zone = Column(String(50), nullable=False)

    min_weight = Column(Float, nullable=False, default=0.0)
    max_weight = Column(Float, nullable=False, default=999999.0)
    cost = Column(Float, nullable=False, default=0.0)
    delivery_days = Column(Integer, nullable=False, default=3)

class RateByZone(Base):
    __tablename__ = "rates_by_zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rate = Column(String(255), nullable=True)
    product_identifier = Column(String(36), nullable=False)

    zone_id = Column(
        String(36),
        ForeignKey("delivery_zones.id", ondelete="RESTRICT"),
        nullable=False,
    )

    zone = relationship("DeliveryZone")

    
    @property
    def zone_code(self):
        return self.zone.zone_code if self.zone else None

    is_shipping_allowed = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    added_by = Column(String(36), nullable=True)
    updated_by = Column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "product_identifier",
            "zone_id",
            name="uq_product_zone",
        ),
        Index("ix_rates_by_zones_zone_id", "zone_id"),
    )


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_code = Column(String(50), nullable=False)   # NOT UNIQUE
    zone_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    added_by = Column(String(36), nullable=True)
    updated_by = Column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_delivery_zones_zone_code", "zone_code"),
    )

class PostcodeZone(Base):
    __tablename__ = "postcode_zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    postcode = Column(String(10), nullable=False, unique=True)

    zone_id = Column(
        String(36),
        ForeignKey("delivery_zones.id", ondelete="RESTRICT"),
        nullable=False,
    )

    zone = relationship("DeliveryZone")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    added_by = Column(String(36), nullable=True)
    updated_by = Column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_postcode_zones_zone_id", "zone_id"),
    )
