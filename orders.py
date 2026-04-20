# app/crud/orders.py
from sqlalchemy import select, and_, or_, String
from typing import Dict
from datetime import datetime
from sqlalchemy import func
import httpx
import os
from dotenv import load_dotenv
from fastapi import HTTPException
import pandas as pd
import asyncio
from functools import lru_cache
from typing import Optional, Any, List
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import json
from models.activity_log import OrderActivityLog
from models.orders import (
    OrderStatus,
    Order,
    OrderItem,
    OrderItemTracking,
    OrderDetails,
    OrderReturn,
    PaymentStatus,
)
from models.shipping_partner import ShipmentPartner


VALID_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "status",
    "payment_status",
    "total_amount",
    "order_number",
    "warehouse_id",
    "courier",
    "tracking_number",
    "actual_delivery_date",
    "items_count",
    "total_saving",
    "shipped_at",
}

EXPORT_PATH = "exports"
os.makedirs(EXPORT_PATH, exist_ok=True)
load_dotenv()


PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL")
PAYMENT_CALL_TIMEOUT = os.getenv("PAYMENT_CALL_TIMEOUT")
PRODUCT_SERVICE_URL = os.getenv(
    "PRODUCT_URL",
    "https://shopper-beats-products-877627218975.australia-southeast2.run.app",
)


def log_activity(
    db,
    order_id: str,
    action: str,
    user_id: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    description: Optional[str] = None,
):
    """
    Log an activity for an order.
    """
    log = OrderActivityLog(
        order_id=order_id,
        action=action,
        user_id=user_id,
        status_from=status_from,
        status_to=status_to,
        description=description,
    )
    db.add(log)
    # We await flush/commit in the caller usually, or here if standalone.
    # Safe to just add to session if part of larger transaction.
    return log


PRODUCT_BASE_URL = os.getenv(
    "PRODUCT_BASE_URL",
    "https://shopper-beats-products-877627218975.australia-southeast2.run.app",
)


async def handle_inventory(
    action: str,
    items: list[OrderItem],
    warehouse_id: Optional[str] = None,
    token: Optional[str] = None,
):
    """
    Call Product Service to Lock/Release/Restock inventory.
    action: "lock", "release", "restock"
    """
    if not items:
        return

    # Prepare payload
    payload = {
        "action": action,
        "warehouse_id": warehouse_id,
        "items": [
            {
                "product_id": i.product_id,
                "quantity": i.quantity,
                "sku": i.sku,
                "reference_id": str(i.order_id) if i.order_id else None,
                "reference_type": "order",
            }
            for i in items
        ],
    }

    url = f"{PRODUCT_BASE_URL}/api/v1/warehouse/inventory/batch"
    print("url", url)
    print("payload", payload)

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # If using authorized token, pass it headers
            # response = await client.post(url, json=payload, headers=headers)

            # For now assuming internal service-to-service call might not need user token
            # or uses a service secret. Using simple post for now.
            response = await client.put(url, json=payload)
            response.raise_for_status()

        except httpx.HTTPStatusError as e:
            # Parse error if possible
            error_detail = e.response.text
            print(f"Inventory {action} failed: {error_detail}")
            raise HTTPException(
                status_code=400, detail=f"Inventory update failed: {error_detail}"
            )
        except Exception as e:
            print(f"Inventory Service Error: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to contact inventory service: {str(e)}"
            )


from service.email_service import (
    send_order_shipped_email,
    send_order_delivered_email,
    send_order_completed_email,
    send_tracking_updated_email,
)


async def update_order_status_logic(
    db,
    order: Order,
    new_status: OrderStatus,
    user_id: Optional[str] = None,
    notes: Optional[str] = None,
    tracking_number: Optional[str] = None,
    courier: Optional[str] = None,
    items: Optional[List[OrderItem]] = None,
):
    """
    Centralized logic for updating order status.
    Handles transitions, validations, inventory triggers, and logging.
    """
    old_status = order.status

    # transitions validation could go here
    # e.g. if old_status == CANCELLED and new_status != REFUNDED: error
    print("old_status", old_status)
    print("new_status", new_status)
    order.status = new_status

    # Update items status to match order status, unless it's a partial state
    if new_status not in [
        OrderStatus.PARTIALLY_SHIPPED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.PARTIALLY_REFUNDED,
    ]:
        for item in order.items:
            if item.status != OrderStatus.CANCELLED:
                item.status = new_status
    if notes:
        order.notes = (order.notes or "") + f"\n[{datetime.now()}] {notes}"

    # Handle specific status actions
    if new_status == OrderStatus.UNSHIPPED and old_status not in [
        OrderStatus.PENDING,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
    ]:
        # Lock inventory when order is ready for shipment
        # Only lock if coming from a non-reserved state (e.g. CANCELLED)
        await handle_inventory("lock", order.items, warehouse_id=order.warehouse_id)

    elif new_status == OrderStatus.SHIPPED:
        if tracking_number:
            order.tracking_number = tracking_number
        if courier:
            order.courier = courier
            # Try to link courier_id for tracking link
            cp_result = await db.execute(
                select(ShipmentPartner).where(ShipmentPartner.name.ilike(courier))
            )
            partner = cp_result.scalar_one_or_none()
            if partner:
                order.courier_id = partner.id

        if items is None:
            for item in order.items:
                if item.status != OrderStatus.CANCELLED and tracking_number:
                    tracking_record = OrderItemTracking(
                        order_item_id=item.id,
                        quantity_shipped=item.quantity,
                        tracking_number=tracking_number,
                        courier=courier,
                        courier_id=order.courier_id,
                    )
                    db.add(tracking_record)

        # Send Email
        try:
            send_order_shipped_email(order, items=items)
        except Exception as e:
            print(f"Failed to send email: {e}")

        # Track ship date
        if not order.shipped_at:
            order.shipped_at = datetime.now()

    elif new_status == OrderStatus.PARTIALLY_SHIPPED:
        if tracking_number:
            order.tracking_number = tracking_number
        if courier:
            order.courier = courier
            cp_result = await db.execute(
                select(ShipmentPartner).where(ShipmentPartner.name.ilike(courier))
            )
            partner = cp_result.scalar_one_or_none()
            if partner:
                order.courier_id = partner.id

        if items is None:
            for item in order.items:
                if item.status != OrderStatus.CANCELLED and tracking_number:
                    tracking_record = OrderItemTracking(
                        order_item_id=item.id,
                        quantity_shipped=item.quantity,
                        tracking_number=tracking_number,
                        courier=courier,
                        courier_id=order.courier_id,
                    )
                    db.add(tracking_record)

        # Track ship date
        if not order.shipped_at:
            order.shipped_at = datetime.now()

        # Send Email for tracking update
        try:
            send_tracking_updated_email(order, items=items)
        except Exception as e:
            print(f"Failed to send email: {e}")

    elif new_status == OrderStatus.DELIVERED:
        if not order.actual_delivery_date:
            order.actual_delivery_date = datetime.now()

        # Send Email
        try:
            send_order_delivered_email(order)
        except Exception as e:
            print(f"Failed to send email: {e}")

    elif new_status == OrderStatus.COMPLETED:
        order.completed_at = datetime.now()

        # Send Email
        try:
            send_order_completed_email(order)
        except Exception as e:
            print(f"Failed to send email: {e}")

    elif new_status == OrderStatus.CANCELLED:
        # Release stock
        await handle_inventory("release", order.items, warehouse_id=order.warehouse_id)
        order.cancellation_reason = notes

    elif new_status == OrderStatus.RETURNED:
        # potentially restock or wait for QC
        order.return_reason = notes

    elif new_status == OrderStatus.REFUNDED:
        # Ensure refund logic is triggered
        pass

    elif new_status in [
        OrderStatus.REPLACEMENT,
        OrderStatus.RETURN_REQUESTED,
        OrderStatus.REPLACEMENT_REQUESTED,
    ]:
        # Specific tracking for these statuses
        pass
    print("Log order", order)
    # Log activity
    await log_activity(
        db,
        order.id,
        action=f"Status Update: {new_status.value}",
        user_id=user_id,
        status_from=old_status.value,
        status_to=new_status.value,
        description=notes,
    )
    print("Log order 1", order)

    return order


def build_order_filters(params):
    filters = []
    if params.get("from_date"):
        filters.append(Order.created_at >= datetime.fromisoformat(params["from_date"]))
    if params.get("to_date"):
        filters.append(Order.created_at <= datetime.fromisoformat(params["to_date"]))
    if params.get("status"):
        statuses = [s.strip().lower() for s in params["status"].split(",")]
        filters.append(Order.status.in_(statuses))
    if params.get("warehouse_id"):
        filters.append(Order.warehouse_id == params["warehouse_id"])
    if params.get("courier"):
        filters.append(Order.courier.ilike(f"%{params['courier']}%"))
    if params.get("supplier_id"):
        filters.append(Order.supplier_id == params["supplier_id"])
    if params.get("brand"):
        filters.append(Order.brand.ilike(f"%{params['brand']}%"))
    if params.get("min_total"):
        filters.append(Order.total_amount >= float(params["min_total"]))
    if params.get("max_total"):
        filters.append(Order.total_amount <= float(params["max_total"]))
    if params.get("q"):
        q_val = params["q"].strip()
        q = f"%{q_val}%"
        search_field = params.get("search_field", "all")

        if search_field == "order_id":
            filters.append(Order.order_number.ilike(q))
        elif search_field == "customer_name" or search_field == "buyer_name":
            filters.append(Order.order_details.has(OrderDetails.customer_name.ilike(q)))
        elif search_field == "sku" or search_field == "product_code":
            filters.append(Order.items.any(OrderItem.sku.ilike(q)))
        elif search_field == "product_id":
            filters.append(Order.items.any(OrderItem.product_id.ilike(q)))
        elif search_field == "tracking_id":
            filters.append(Order.tracking_number.ilike(q))
        elif search_field == "item_name":
            filters.append(Order.items.any(OrderItem.name.ilike(q)))
        elif search_field == "tags":
            # Assuming tags is a JSON list or similar
            filters.append(Order.tags.cast(String).ilike(q))
        else:
            # General search
            filters.append(
                or_(
                    Order.order_number.ilike(q),
                    Order.order_details.has(OrderDetails.customer_name.ilike(q)),
                    Order.items.any(OrderItem.sku.ilike(q)),
                    Order.items.any(OrderItem.name.ilike(q)),
                    Order.tracking_number.ilike(q),
                )
            )

    if params.get("vendor_id"):
        filters.append(Order.items.any(OrderItem.vendor_id == params["vendor_id"]))

    return filters


async def get_orders(db, params, user_id, session_token):
    print(user_id, "IN Get Orders")
    # stmt = select(Order)
    stmt = select(Order).options(
        selectinload(Order.order_details),
        selectinload(Order.items),
        selectinload(Order.courier_partner),
    )
    filters = build_order_filters(params)
    if filters:
        stmt = stmt.where(and_(*filters))
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)
    else:
        stmt = stmt.where(Order.session_token == session_token)

    # sort + pagination
    sort_by = params.get("sort_by", "created_at")
    if sort_by not in VALID_SORT_FIELDS:
        sort_by = "created_at"
    sort_dir = params.get("sort_dir", "desc")
    sort_col = getattr(Order, sort_by)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    page = int(params.get("page", 1))
    per_page = min(int(params.get("per_page", 25)), 1000)
    stmt = stmt.limit(per_page).offset((page - 1) * per_page)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_orders_admin(db: Any, params: Dict[str, Any]):
    """
    Retrieve all orders from the database (admin-level view).
    Ignores any user/session restrictions — returns every order no matter what.

    Applies optional filters, sorting, and pagination based on params.
    """
    # Base query with eager loading of related order_details and items
    stmt = select(Order).options(
        selectinload(Order.order_details),
        selectinload(Order.items),
        selectinload(Order.courier_partner),
    )

    # Apply dynamic filters if any (e.g., status, date range, etc.)
    filters = build_order_filters(params)
    if filters:
        stmt = stmt.where(and_(*filters))

    # Sorting
    sort_by = params.get("sort_by", "created_at")
    if sort_by not in VALID_SORT_FIELDS:
        sort_by = "created_at"
    sort_dir = params.get("sort_dir", "desc")

    # Safely get the column attribute (add validation in production if needed)
    sort_col = getattr(Order, sort_by)

    if sort_dir == "desc":
        stmt = stmt.order_by(sort_col.desc())
    else:
        stmt = stmt.order_by(sort_col.asc())

    # Pagination
    page = max(int(params.get("page", 1)), 1)  # Prevent page <= 0
    per_page = min(int(params.get("per_page", 25)), 1000)  # Cap at 1000

    stmt = stmt.limit(per_page).offset((page - 1) * per_page)

    # Execute and return all matching orders
    result = await db.execute(stmt)
    return result.scalars().all()


async def count_orders_admin(db: Any, params: Dict[str, Any]):
    filters = build_order_filters(params)
    stmt = select(func.count()).select_from(Order)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    return result.scalar()


async def count_orders(db, params, user_id, session_token):

    filters = build_order_filters(params)
    stmt = select(func.count()).select_from(Order)
    if filters:
        stmt = stmt.where(and_(*filters))
    if user_id:
        stmt = stmt.where(Order.user_id == user_id)
    else:
        stmt = stmt.where(Order.session_token == session_token)
    result = await db.execute(stmt)
    return result.scalar()


async def call_payment_service(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call your payment microservice to create a payment intent/charge.
    Adjust headers/auth as needed. Returns JSON dict from payment service.
    """
    timeout = float(PAYMENT_CALL_TIMEOUT) if PAYMENT_CALL_TIMEOUT else 10.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        url = f"{PAYMENT_SERVICE_URL}/api/v1/payment/initiate"
        resp = await client.post(url, json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502, detail=f"Payment service error: {e.response.text}"
            )
        return resp.json()


async def call_payment_refund(
    payload: Dict[str, Any], idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call payment microservice to process a refund.
    """
    timeout = float(PAYMENT_CALL_TIMEOUT) if PAYMENT_CALL_TIMEOUT else 10.0
    headers = {}
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    async with httpx.AsyncClient(timeout=timeout) as client:
        url = f"{PAYMENT_SERVICE_URL}/api/v1/payment/refund"
        resp = await client.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502, detail=f"Payment service error: {e.response.text}"
            )
        return resp.json()


@lru_cache(maxsize=1)
def load_pincode_file(filepath: str):
    return pd.read_csv(
        filepath,
        sep=r"\s+",
        header=None,
        usecols=[0, 1, 2, 3],
        names=["country", "pincode", "place", "state"],
        dtype={"pincode": str},
    )


async def validate_pincode_from_file(
    pincode: str, filepath: str
) -> Optional[Dict[str, Any]]:
    if not pincode or not filepath:
        return

    def _work():
        try:

            df = load_pincode_file(filepath)

            target = str(pincode).strip()

            row = df[df["pincode"].str.strip() == target]
            return None if row.empty else row.iloc[0].to_dict()

        except Exception as e:
            print("Error reading file:", e)
            return None

    return await asyncio.to_thread(_work)


async def export_orders_csv(orders):
    file_path = os.path.join(EXPORT_PATH, "orders_export.csv")

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # CSV headers
        writer.writerow(
            [
                "order_id",
                "order_number",
                "status",
                "payment_status",
                "subtotal",
                "tax_amount",
                "discount_amount",
                "total_saving",
                "total_amount",
                "currency",
                "brand",
                "warehouse_id",
                "courier",
                "created_at",
                # Shipping
                "shipping_first_name",
                "shipping_last_name",
                "shipping_address",
                "shipping_city",
                "shipping_state",
                "shipping_postal_code",
                "shipping_country",
                "shipping_phone",
                # Billing
                "billing_first_name",
                "billing_last_name",
                "billing_address",
                "billing_city",
                "billing_state",
                "billing_postal_code",
                "billing_country",
                "billing_phone",
                # Items JSON
                "items",
            ]
        )

        for o in orders:
            d = o.order_details

            writer.writerow(
                [
                    o.id,
                    o.order_number,
                    o.status,
                    o.payment_status,
                    o.subtotal,
                    o.tax_amount,
                    o.discount_amount,
                    o.total_saving,
                    o.total_amount,
                    o.currency,
                    o.brand,
                    o.warehouse_id,
                    o.courier,
                    o.created_at.isoformat() if o.created_at else None,
                    # shipping
                    d.shipping_first_name if d else None,
                    d.shipping_last_name if d else None,
                    d.shipping_address if d else None,
                    d.shipping_city if d else None,
                    d.shipping_state if d else None,
                    d.shipping_postal_code if d else None,
                    d.shipping_country if d else None,
                    d.shipping_phone if d else None,
                    # billing
                    d.billing_first_name if d else None,
                    d.billing_last_name if d else None,
                    d.billing_address if d else None,
                    d.billing_city if d else None,
                    d.billing_state if d else None,
                    d.billing_postal_code if d else None,
                    d.billing_country if d else None,
                    d.billing_phone if d else None,
                    json.dumps(
                        d.customer_snapshot.get("products")
                        if d and d.customer_snapshot
                        else []
                    ),
                ]
            )

    return file_path


async def export_orders_report(db: AsyncSession, params: Dict[str, Any] = None):
    stmt = select(Order).options(
        selectinload(Order.order_details),
        selectinload(Order.items),
        selectinload(Order.courier_partner),
    )

    if params:
        filters = build_order_filters(params)
        if filters:
            stmt = stmt.where(and_(*filters))

    result = await db.execute(stmt.order_by(Order.created_at.desc()))

    orders = result.scalars().all()

    rows = []

    for order in orders:
        details = order.order_details

        for item in order.items:
            dt = order.created_at

            rows.append(
                {
                    # Order Details
                    "Date": dt.strftime("%d-%m-%Y") if dt else None,
                    "Time(AM/PM)": dt.strftime("%I:%M:%S %p") if dt else None,
                    "Order ID": order.order_number,
                    # Shipping Customer
                    "First Name": getattr(details, "shipping_first_name", None),
                    "Last Name": getattr(details, "shipping_last_name", None),
                    "Full Name": (
                        f"{getattr(details, 'shipping_first_name', '') or ''} "
                        f"{getattr(details, 'shipping_last_name', '') or ''}"
                    ).strip(),
                    "Address 1": (
                        f"{getattr(details, 'shipping_apartment', '') or ''}, "
                        f"{getattr(details, 'shipping_house_no', '') or ''}"
                    ).strip(", "),
                    "Address 2": getattr(details, "shipping_address", None),
                    "City": getattr(details, "shipping_city", None),
                    "State": getattr(details, "shipping_state", None),
                    "Zipcode": getattr(details, "shipping_postal_code", None),
                    "Country": getattr(details, "shipping_country", None),
                    "Phone": getattr(details, "shipping_phone", None),
                    "Email": getattr(details, "customer_email", None),
                    "Brand Name": order.brand,
                    # Product
                    "Vendor": None,
                    "Item Name": item.name,
                    "Variation": None,
                    "SKU": item.sku,
                    "QTY": item.quantity,
                    "Unit Price": float(item.unit_price) if item.unit_price else None,
                    "Sale Price": None,
                    "Shipping Price": (
                        float(order.shipping_cost) if order.shipping_cost else None
                    ),
                    "Total Price": (
                        float(order.total_amount) if order.total_amount else None
                    ),
                    "Item Weight": None,
                    # Vendor
                    "Vendor Name": None,
                    # Warehouse
                    "Ship From": "SBAU",
                    # Tracking
                    "Tracking #": order.tracking_number,
                    "Carrier": order.courier,
                    "Carrier Code": order.courier_id,
                    "Tracking Link": order.tracking_link,
                    # Status
                    "Order Status": order.status.value if order.status else None,
                    "Order Tag": None,
                    # Payment
                    "Payment Details": (
                        order.payment_status.value if order.payment_status else None
                    ),
                    # Billing
                    "Billing First Name": getattr(details, "billing_first_name", None),
                    "Billing Last Name": getattr(details, "billing_last_name", None),
                    "Billing Full Name": (
                        f"{getattr(details, 'billing_first_name', '') or ''} "
                        f"{getattr(details, 'billing_last_name', '') or ''}"
                    ).strip(),
                    "Billing Address 1": (
                        f"{getattr(details, 'billing_apartment', '') or ''}, "
                        f"{getattr(details, 'billing_house_no', '') or ''}"
                    ).strip(", "),
                    "Billing Address 2": getattr(details, "billing_address", None),
                    "Billing City": getattr(details, "billing_city", None),
                    "Billing State": getattr(details, "billing_state", None),
                    "Billing Zipcode": getattr(details, "billing_postal_code", None),
                    "Billing Country": getattr(details, "billing_country", None),
                    "Billing Phone": getattr(details, "billing_phone", None),
                }
            )

    return pd.DataFrame(rows)


async def get_orders_without_pagination(db, params):
    stmt = select(Order).options(
        selectinload(Order.order_details),
        selectinload(Order.items),
        selectinload(Order.courier_partner),
    )

    filters = build_order_filters(params)
    if filters:
        stmt = stmt.where(and_(*filters))

    sort_by = params.get("sort_by", "created_at")
    if sort_by not in VALID_SORT_FIELDS:
        sort_by = "created_at"
    sort_dir = params.get("sort_dir", "desc")
    sort_col = getattr(Order, sort_by)
    stmt = stmt.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    result = await db.execute(stmt)
    return result.scalars().all()


async def create_replacement_order(
    db: AsyncSession, original_order: Order, return_req: OrderReturn
):
    """
    Creates a new replacement order based on a return request.
    Clones shipping details and specific items being replaced.
    """
    # 1. Create the new Order record
    new_order = Order(
        original_order_id=original_order.id,
        warehouse_id=original_order.warehouse_id,
        supplier_id=original_order.supplier_id,
        brand=original_order.brand,
        currency=original_order.currency,
        user_id=original_order.user_id,
        session_token=original_order.session_token,
        status=OrderStatus.PENDING,
        payment_status=PaymentStatus.PAID,  # Replacement is pre-paid by the original order
        subtotal=0,
        shipping_cost=0,
        tax_amount=0,
        discount_amount=0,
        total_amount=0,
        items_count=sum(item.quantity for item in return_req.items),
        notes=f"Replacement for Order {original_order.order_number} (Return ID: {return_req.id})",
        source=original_order.source,
        tags=["replacement"],
    )
    db.add(new_order)
    await db.flush()

    # 2. Clone OrderDetails
    orig_details = original_order.order_details
    new_details = OrderDetails(
        order_id=new_order.id,
        customer_name=orig_details.customer_name,
        customer_email=orig_details.customer_email,
        customer_phone=orig_details.customer_phone,
        shipping_first_name=orig_details.shipping_first_name,
        shipping_last_name=orig_details.shipping_last_name,
        shipping_company=orig_details.shipping_company,
        shipping_address=orig_details.shipping_address,
        shipping_apartment=orig_details.shipping_apartment,
        shipping_city=orig_details.shipping_city,
        shipping_state=orig_details.shipping_state,
        shipping_country=orig_details.shipping_country,
        shipping_postal_code=orig_details.shipping_postal_code,
        shipping_phone=orig_details.shipping_phone,
        shipping_house_no=orig_details.shipping_house_no,
        landmark=orig_details.landmark,
        billing_first_name=orig_details.billing_first_name,
        billing_last_name=orig_details.billing_last_name,
        billing_company=orig_details.billing_company,
        billing_address=orig_details.billing_address,
        billing_apartment=orig_details.billing_apartment,
        billing_city=orig_details.billing_city,
        billing_state=orig_details.billing_state,
        billing_country=orig_details.billing_country,
        billing_postal_code=orig_details.billing_postal_code,
        billing_phone=orig_details.billing_phone,
        billing_house_no=orig_details.billing_house_no,
        customer_snapshot=orig_details.customer_snapshot,  # potentially update this with new items
    )
    db.add(new_details)

    # 3. Create OrderItems for replacement
    # We need to find the original items to get their correct product metadata/prices
    new_items_list = []
    for ret_item in return_req.items:
        # ret_item.order_item_id should match the ID in original_order.items
        orig_item = next(
            (
                i
                for i in original_order.items
                if i.id == ret_item.order_item_id or i.product_id == ret_item.product_id
            ),
            None,
        )

        new_item = OrderItem(
            order_id=new_order.id,
            product_id=ret_item.product_id,
            name=orig_item.name if orig_item else "Replaced Product",
            sku=orig_item.sku if orig_item else None,
            quantity=ret_item.quantity,
            unit_price=orig_item.unit_price if orig_item else 0,
            total_price=0,  # Financial total for replacement is 0
            status=new_order.status,
            vendor_id=ret_item.vendor_id,
        )
        db.add(new_item)
        new_items_list.append(new_item)

    await db.flush()

    # 4. Lock inventory for new items
    await handle_inventory("lock", new_items_list, warehouse_id=new_order.warehouse_id)

    return new_order


async def update_order_address(
    db: AsyncSession,
    order: Order,
    shipping_addr: Optional[Any] = None,
    billing_addr: Optional[Any] = None,
    user_id: Optional[str] = None,
):
    """
    Update shipping and/or billing addresses for an order.
    Updates OrderDetails fields and the customer_snapshot JSON.
    Logs activity.
    """
    details = order.order_details
    if not details:
        raise HTTPException(status_code=404, detail="Order details not found")

    changes = []
    old_values = {}
    snapshot = (details.customer_snapshot or {}).copy()

    # Mapping of address types and their respective fields in OrderDetails
    # Note: landwark is shared or only for shipping in some models, in OrderDetails it is just 'landmark'
    address_config = {
        "shipping": {
            "data": shipping_addr,
            "fields": [
                "first_name",
                "last_name",
                "company",
                "address",
                "apartment",
                "city",
                "state",
                "country",
                "postal_code",
                "phone",
                "house_no",
                "landmark",
            ],
        },
        "billing": {
            "data": billing_addr,
            "fields": [
                "first_name",
                "last_name",
                "company",
                "address",
                "apartment",
                "city",
                "state",
                "country",
                "postal_code",
                "phone",
                "house_no",
            ],
        },
    }

    for addr_type, config in address_config.items():
        addr_data = config["data"]
        if not addr_data:
            continue

        old_addr = {}
        for field in config["fields"]:
            # Determine attribute name in OrderDetails model
            attr_name = f"{addr_type}_{field}"
            if addr_type == "shipping" and field == "landmark":
                attr_name = "landmark"

            # Save old value and update new one
            old_addr[field] = getattr(details, attr_name)
            setattr(details, attr_name, getattr(addr_data, field))

        old_values[addr_type] = old_addr
        snapshot[f"{addr_type}_address"] = addr_data.model_dump()
        changes.append(f"{addr_type.capitalize()} Address")

    if changes:
        details.customer_snapshot = snapshot

        # Construct a more readable log description
        log_desc = f"Address Update Summary: {', '.join(changes)}."
        if old_values:
            log_desc += "\n\n[Previous Address Data]"
            for addr_type, old_data in old_values.items():
                log_desc += f"\n--- {addr_type.upper()} ---"
                for field, val in old_data.items():
                    log_desc += (
                        f"\n{field.replace('_', ' ').title()}: {val if val else 'N/A'}"
                    )

        await log_activity(
            db,
            order.id,
            action="Address Updated",
            user_id=user_id,
            description=log_desc,
        )

    return order
