# app/models.py
import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Enum,
    Integer,
    Boolean,
    BigInteger,
    Numeric,
)
from sqlalchemy.sql import func
from database import Base
import enum
from sqlalchemy.orm import relationship
import string
import secrets

def generate_order_number(length: int = 10):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

class OrderStatus(enum.Enum):
    PENDING = "pending"
    UNSHIPPED = "unshipped"
    SHIPPED = "shipped"
    PARTIALLY_SHIPPED = "partially_shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    PARTIALLY_RETURNED = "partially_returned"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    REPLACEMENT = "replacement"
    RETURN_REQUESTED = "return_requested"
    REPLACEMENT_REQUESTED = "replacement_requested"
    
    RETURN_REJECTED = "return_rejected"
    REPLACEMENT_REJECTED = "replacement_rejected"
    
    CONFIRMED = "confirmed" # Deprecated
    PROCESSING = "processing" # Deprecated

class PaymentStatus(enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class Order(Base):
    __tablename__ = "orders"

    # Primary Information
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number = Column(String(36), unique=True, index=True, nullable=False, default=generate_order_number)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at = Column(DateTime(timezone=True), nullable=True) # New field
    shipped_at = Column(DateTime(timezone=True), nullable=True) # New field

    # Status Information
    status = Column(
        Enum(OrderStatus), index=True, nullable=False, default=OrderStatus.PENDING
    )
    payment_status = Column(
        Enum(PaymentStatus), index=True, nullable=False, default=PaymentStatus.PENDING
    )

    # Delivery Information
    warehouse_id = Column(String(36), index=True, nullable=True)
    courier_id = Column(String(36), index=True, nullable=True)
    courier = Column(String(100), index=True, nullable=True)
    tracking_number = Column(String(100), nullable=True)
    estimated_delivery_date = Column(DateTime(timezone=True), nullable=True)
    actual_delivery_date = Column(DateTime(timezone=True), nullable=True)

    # Supplier Information
    supplier_id = Column(String(36), index=True, nullable=True)
    brand = Column(String(100), index=True)

# total_amount = subtotal + shipping + tax − discount
    # Financial Information
    subtotal = Column(Numeric(10,2), nullable=True, default=0)
    shipping_cost = Column(Numeric(10,2), nullable=True, default=0)
    tax_amount = Column(Numeric(10,2), nullable=True, default=0)
    discount_amount = Column(Numeric(10,2), nullable=True, default=0)
    total_amount = Column(Numeric(10,2), nullable=True)
    total_saving = Column(Numeric(10,2), nullable=True, default=0)
    refund_amount = Column(Numeric(10,2), nullable=True, default=0) # New field
    currency = Column(String(3), nullable=True, default="INR")  # ISO currency code

    # Order Details
    items_count = Column(Integer, nullable=True)
    is_gift = Column(Boolean, default=False)
    gift_message = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    cancellation_reason = Column(Text, nullable=True) # New field
    return_reason = Column(Text, nullable=True) # New field
    source = Column(
        String(50), nullable=True
    )  # e.g., 'web', 'mobile_app', 'marketplace'
    tags = Column(JSON, nullable=True)

    # ShipStation integration
    shipstation_order_id = Column(BigInteger, nullable=True, index=True)
    shipstation_order_key = Column(String(100), nullable=True)
    shipstation_sync_status = Column(
        String(50), default="pending"
    )  # pending, success, failed
    shipstation_sync_error = Column(Text, nullable=True)
    shipstation_order_status = Column(
        Enum(OrderStatus),
        index=True,
        nullable=False,
        default=OrderStatus.UNSHIPPED,
    )
    # user or session details
    user_id = Column(String(36), index=True, nullable=True)
    session_token = Column(String(36), index=True, nullable=True)
    order_details = relationship(
        "OrderDetails",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    returns = relationship(
        "OrderReturn",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        foreign_keys="OrderReturn.order_id"
    )

    timeline = relationship(
        "OrderTimelineEntry",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderTimelineEntry.created_at.desc()"
    )

    original_order_id = Column(String(36), ForeignKey("orders.id"), nullable=True) # If this is a replacement

    courier_partner = relationship(
        "ShipmentPartner",
        primaryjoin="Order.courier_id == ShipmentPartner.id",
        foreign_keys=[courier_id],
        uselist=False,
        lazy="selectin",
        viewonly=True,
    )

    @property
    def tracking_link(self):
        if self.tracking_number and self.courier_partner and self.courier_partner.tracking_url:
            return self.courier_partner.tracking_url.replace("{tracking_number}", self.tracking_number)
        return None


class OrderDetails(Base):
    __tablename__ = "order_details"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Customer Info
    customer_name = Column(String(100))
    customer_email = Column(String(255))
    customer_phone = Column(String(20))

    # Shipping Fields
    shipping_first_name = Column(String(100), nullable=True)
    shipping_last_name = Column(String(100), nullable=True)
    shipping_company = Column(String(255), nullable=True)
    shipping_address = Column(Text, nullable=True)
    shipping_apartment = Column(String(255), nullable=True)
    shipping_city = Column(String(100), nullable=True)
    shipping_state = Column(String(100), nullable=True)
    shipping_country = Column(String(100), nullable=True)
    shipping_postal_code = Column(String(20), nullable=True)
    shipping_phone = Column(String(20), nullable=True)
    shipping_house_no = Column(String(50), nullable=True)
    landmark = Column(String(255), nullable=True)

    # Billing Fields
    billing_first_name = Column(String(100), nullable=True)
    billing_last_name = Column(String(100), nullable=True)
    billing_company = Column(String(255), nullable=True)
    billing_address = Column(Text, nullable=True)
    billing_apartment = Column(String(255), nullable=True)
    billing_city = Column(String(100), nullable=True)
    billing_state = Column(String(100), nullable=True)
    billing_country = Column(String(100), nullable=True)
    billing_postal_code = Column(String(20), nullable=True)
    billing_phone = Column(String(20), nullable=True)
    billing_house_no = Column(String(50), nullable=True)

    # JSON Snapshot (products, payment method, etc.)
    customer_snapshot = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    order = relationship("Order", back_populates="order_details")

# ---------------------------------------------------------------------------
# OrderItem model – stores each line‑item of an order as a separate row.
# ---------------------------------------------------------------------------
class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False)
    product_id = Column(String(36), nullable=False)
    name = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=True)
    ean_code = Column(String(100), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10,2), nullable=False, default=0)
    total_price = Column(Numeric(10,2), nullable=False, default=0)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    vendor_id = Column(String(36), nullable=True)

    order = relationship("Order", back_populates="items")
    tracking_details = relationship("OrderItemTracking", back_populates="order_item", cascade="all, delete-orphan", lazy="selectin")

class OrderItemTracking(Base):
    __tablename__ = "order_item_trackings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_item_id = Column(Integer, ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity_shipped = Column(Integer, nullable=False, default=1)
    tracking_number = Column(String(100), nullable=True)
    courier = Column(String(100), nullable=True)
    courier_id = Column(String(36), ForeignKey("shipment_partners.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order_item = relationship("OrderItem", back_populates="tracking_details")
    courier_partner = relationship("ShipmentPartner", lazy="selectin", viewonly=True)

    @property
    def tracking_link(self):
        if self.tracking_number and self.courier_partner and self.courier_partner.tracking_url:
            return self.courier_partner.tracking_url.replace("{tracking_number}", self.tracking_number)
        return None

# Add relationship on Order (one‑to‑many)
Order.items = relationship(
    "OrderItem",
    back_populates="order",
    cascade="all, delete-orphan",
    lazy="selectin",
)


class OrderDiscount(Base):
    __tablename__ = "order_discounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    promotion_code = Column(String(50), nullable=True)
    promotion_type = Column(String(50), nullable=True)  # e.g., 'coupon', 'automatic', 'manual'
    amount = Column(Numeric(10,2), nullable=False, default=0)
    description = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="discounts")


class OrderItemDiscount(Base):
    __tablename__ = "order_item_discounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_item_id = Column(
        Integer,
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    promotion_code = Column(String(50), nullable=True)
    promotion_type = Column(String(50), nullable=True)
    amount = Column(Numeric(10,2), nullable=False, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order_item = relationship("OrderItem", back_populates="discounts")


# Add relationships to existing models
Order.discounts = relationship(
    "OrderDiscount",
    back_populates="order",
    cascade="all, delete-orphan",
    lazy="selectin",
)

OrderItem.discounts = relationship(
    "OrderItemDiscount",
    back_populates="order_item",
    cascade="all, delete-orphan",
    lazy="selectin",
)

class ReturnStatus(enum.Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFUNDED = "refunded"
    REPLACED = "replaced"


class OrderReturn(Base):
    __tablename__ = "order_returns"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(36), index=True, nullable=True)
    status = Column(Enum(ReturnStatus), default=ReturnStatus.REQUESTED, index=True)
    return_type = Column(String(20), default="refund") # Added: refund or replacement
    reason = Column(Text, nullable=True)
    customer_comment = Column(Text, nullable=True)
    admin_notes = Column(Text, nullable=True)
    refund_amount = Column(Numeric(10, 2), nullable=True, default=0)
    
    # Return Address Fields
    return_first_name = Column(String(100), nullable=True)
    return_last_name = Column(String(100), nullable=True)
    return_company = Column(String(255), nullable=True)
    return_address = Column(Text, nullable=True)
    return_apartment = Column(String(255), nullable=True)
    return_city = Column(String(100), nullable=True)
    return_state = Column(String(100), nullable=True)
    return_country = Column(String(100), nullable=True)
    return_postal_code = Column(String(20), nullable=True)
    return_phone = Column(String(20), nullable=True)
    return_house_no = Column(String(50), nullable=True)
    return_landmark = Column(String(255), nullable=True)
    replacement_order_id = Column(String(36), ForeignKey("orders.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items = relationship("OrderReturnItem", back_populates="return_request", cascade="all, delete-orphan", lazy="selectin")
    order = relationship("Order", back_populates="returns", foreign_keys=[order_id])
    replacement_order = relationship("Order", foreign_keys=[replacement_order_id])


class OrderReturnItem(Base):
    __tablename__ = "order_return_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    return_id = Column(
        String(36),
        ForeignKey("order_returns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_item_id = Column(Integer, nullable=False) # Not FK to avoid complex cascades, or can be FK
    product_id = Column(String(36), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    reason = Column(Text, nullable=True)
    vendor_id = Column(String(36), nullable=True)

    return_request = relationship("OrderReturn", back_populates="items")


class OrderTimelineEntry(Base):
    __tablename__ = "order_timeline_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    text = Column(Text, nullable=False)
    attachments = Column(JSON, nullable=True) # list of dicts: [{"url": "...", "name": "..."}]
    user_id = Column(String(36), nullable=True) # Admin ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="timeline")
