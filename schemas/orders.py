from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from models.orders import OrderStatus
from pydantic import field_validator, model_validator


# -------------------------------------------------------------------
# Address models
# -------------------------------------------------------------------


class OrderAddress(BaseModel):
    """Used for shipping and billing addresses."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    apartment: Optional[str] = None
    address: str
    house_no: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    country: str
    postal_code: str
    phone: Optional[str] = None

    model_config = {"extra": "ignore"}


class OrderAddressUpdate(BaseModel):
    shipping: Optional[OrderAddress] = None
    billing: Optional[OrderAddress] = None


# -------------------------------------------------------------------
# Payment model
# -------------------------------------------------------------------


class PaymentMethod(BaseModel):
    type: str
    provider: str
    transaction_id: Optional[str] = None
    status: str = "pending"


# -------------------------------------------------------------------
# Base Order
# -------------------------------------------------------------------


class OrderBase(BaseModel):
    order_number: Optional[str] = None

    # Logistics
    warehouse_id: Optional[str] = None
    courier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_link: Optional[str] = None

    # Supplier information
    supplier_id: Optional[str] = None
    brand: Optional[str] = None

    # Money
    subtotal: Decimal = Decimal(0)
    shipping_cost: Decimal = Decimal(0)
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    total_amount: Decimal = Decimal(0)
    total_saving: Decimal = Decimal(0)
    currency: str = Field(default="INR", max_length=3)

    # Details
    items_count: int
    is_gift: bool = False
    gift_message: Optional[str] = None
    notes: Optional[str] = None

    # Meta
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    items: Optional[List[Dict[str, Any]]] = None

    model_config = {"from_attributes": True}


class OrderDetailsBillingSchema(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None

    class Config:
        from_attributes = True


class OrderDetailsShippingSchema(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None

    class Config:
        from_attributes = True


class OrderDetailsSchema(BaseModel):
    id: str

    # customer info
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    # shipping fields
    shipping_first_name: Optional[str] = None
    shipping_last_name: Optional[str] = None
    shipping_company: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_apartment: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_state: Optional[str] = None
    shipping_country: Optional[str] = None
    shipping_postal_code: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_house_no: Optional[str] = None
    landmark: Optional[str] = None

    # billing fields
    billing_first_name: Optional[str] = None
    billing_last_name: Optional[str] = None
    billing_company: Optional[str] = None
    billing_address: Optional[str] = None
    billing_apartment: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_country: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_phone: Optional[str] = None
    billing_house_no: Optional[str] = None

    # full snapshot JSON
    customer_snapshot: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


# -------------------------------------------------------------------
# Create Order
# -------------------------------------------------------------------


class OrderDiscountSchema(BaseModel):
    promotion_code: Optional[str] = None
    promotion_type: Optional[str] = None  # e.g., 'coupon', 'automatic'
    amount: Decimal
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderItemDiscountSchema(BaseModel):
    promotion_code: Optional[str] = None
    promotion_type: Optional[str] = None
    amount: Decimal

    model_config = {"from_attributes": True}


class OrderCreate(OrderBase):
    """Schema for new order creation."""

    # Addresses
    shipping: OrderAddress
    billing: Optional[OrderAddress] = None
    shipping_same_as_billing: bool = False

    # Payment
    payment_method: PaymentMethod

    # Customer
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    shipping_details: Optional[OrderDetailsShippingSchema] = None

    # Promotions/Coupons
    promotions: Optional[List[OrderDiscountSchema]] = []


# -------------------------------------------------------------------
# Update Order (PATCH)
# -------------------------------------------------------------------


class OrderUpdate(BaseModel):
    status: Optional[str] = None
    payment_status: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[datetime] = None
    actual_delivery_date: Optional[datetime] = None

    # Financials (partial updates allowed)
    subtotal: Optional[Decimal] = Decimal(0)
    shipping_cost: Optional[Decimal] = Decimal(0)
    tax_amount: Optional[Decimal] = Decimal(0)
    discount_amount: Optional[Decimal] = Decimal(0)
    total_amount: Optional[Decimal] = Decimal(0)
    total_saving: Optional[Decimal] = Decimal(0)

    # Order info
    items_count: Optional[int] = None
    is_gift: Optional[bool] = None
    gift_message: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None

    model_config = {"from_attributes": True}


class OrderItemTrackingSchema(BaseModel):
    id: str
    quantity_shipped: int
    tracking_number: Optional[str] = None
    courier: Optional[str] = None
    tracking_link: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderItemSchema(BaseModel):
    id: int
    product_id: str
    name: str
    vendor_id: Optional[str] = None
    sku: Optional[str] = None
    ean_code: Optional[str] = None
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    status: OrderStatus
    available_actions: List[str] = []
    discounts: List[OrderItemDiscountSchema] = []
    tracking_details: List[OrderItemTrackingSchema] = []

    model_config = {"from_attributes": True}


class OrderTimelineEntrySchema(BaseModel):
    id: str
    text: str
    attachments: Optional[List[Dict[str, Any]]] = None
    user_id: Optional[str] = None
    created_at: datetime
    type: str = "custom"

    class Config:
        from_attributes = True


# -------------------------------------------------------------------
# Output Schema
# -------------------------------------------------------------------


class OrderMinimalOut(OrderBase):
    id: str
    order_number: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    estimated_delivery_date: Optional[datetime] = None
    actual_delivery_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    order_details: Optional[OrderDetailsSchema] = None
    items: List[OrderItemSchema] = []
    refund_amount: Optional[Decimal] = Decimal(0)
    total_saving: Optional[Decimal] = Decimal(0)
    cancellation_reason: Optional[str] = None
    return_reason: Optional[str] = None
    # shipstation
    shipstation_order_id: Optional[int] = None
    shipstation_order_key: Optional[str] = None
    shipstation_order_status: Optional[str] = None
    available_actions: List[str] = []
    discounts: List[OrderDiscountSchema] = []
    timeline: List[OrderTimelineEntrySchema] = []
    original_order_id: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderOut(OrderMinimalOut):
    returns: List["OrderReturnMinimalSchema"] = []


# -------------------------------------------------------------------
# Status Update
# -------------------------------------------------------------------


class OrderTagsUpdate(BaseModel):
    tags: Optional[List[str]] = None


class PaymentStatusUpdate(BaseModel):
    payment_status: str
    transaction_id: Optional[str] = None
    provider: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("payment_status")
    def validate_status(cls, v):
        try:
            from models.orders import PaymentStatus

            PaymentStatus(v.lower())
            return v.lower()
        except ValueError:
            valid = [s.value for s in PaymentStatus]
            raise ValueError(
                f"Invalid payment status. Must be one of: {', '.join(valid)}"
            )


class RetryPaymentRequest(BaseModel):
    payment_method: PaymentMethod


class OrderStatusUpdate(BaseModel):
    status: str = Field(
        description="Order status",
        examples=[
            "pending",
            "confirmed",
            "unshipped",
            "shipped",
            "delivered",
            "completed",
            "cancelled",
            "returned",
            "partially_returned",
            "refunded",
            "partially_refunded",
            "replacement",
            "return_requested",
            "replacement_requested",
        ],
    )
    notes: Optional[str] = None
    actual_delivery_date: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    return_reason: Optional[str] = None
    tracking_number: Optional[str] = None
    courier: Optional[str] = None
    courier_id: Optional[str] = None

    @field_validator("status")
    def validate_status(cls, v):
        try:
            OrderStatus(v.lower())
            return v.lower()
        except ValueError:
            raise ValueError(
                f"Invalid status. Must be one of: {', '.join(s.value for s in OrderStatus)}"
            )

    @model_validator(mode="after")
    def validate_tracking_and_delivery(self):
        if self.status == "delivered" and not self.actual_delivery_date:
            raise ValueError(
                "actual_delivery_date is required when status is 'delivered'"
            )

        if self.status == "shipped":
            if not self.tracking_number:
                raise ValueError("tracking_number is required when status is 'shipped'")
            if not self.courier:
                raise ValueError("courier is required when status is 'shipped'")

        return self


class AddReviewRequest(BaseModel):
    product_id: str
    rating: float
    comment: str
    title: str
    images: Optional[List[str]] = None


class ReturnRequest(BaseModel):
    reason: str
    return_type: str = "refund"  # refund or replacement
    customer_comment: Optional[str] = None
    return_address: Optional[OrderAddress] = None


class OrderReturnItemSchema(BaseModel):
    id: str
    product_id: str
    vendor_id: Optional[str] = None
    quantity: int
    reason: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderReturnMinimalSchema(BaseModel):
    id: str
    order_id: str
    status: str
    return_type: str = "refund"
    reason: Optional[str] = None
    customer_comment: Optional[str] = None
    refund_amount: Optional[Decimal] = None

    # Return Address Fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company: Optional[str] = None
    address: Optional[str] = None
    apartment: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    phone: Optional[str] = None
    house_no: Optional[str] = None
    landmark: Optional[str] = None

    created_at: datetime
    updated_at: datetime
    items: List[OrderReturnItemSchema] = []
    available_actions: List[str] = []
    replacement_order_id: Optional[str] = None

    model_config = {"from_attributes": True}


class OrderReturnSchema(OrderReturnMinimalSchema):
    order: Optional[OrderMinimalOut] = None


class ProcessReturnRequest(BaseModel):
    action: str = Field(
        ..., description="approve, reject, refund, replace, or returned"
    )
    refund_amount: Optional[Decimal] = None
    admin_notes: Optional[str] = None

    @field_validator("action")
    def validate_action(cls, v):
        if v.lower() not in ["approve", "reject", "refund", "replace", "returned"]:
            raise ValueError(
                "Action must be 'approve', 'reject', 'refund', 'replace', or 'returned'"
            )
        return v.lower()
