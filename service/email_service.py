import logging
from typing import Any, List
from dotenv import load_dotenv
from service.admin_email_client import send_template_email

load_dotenv()

logger = logging.getLogger(__name__)


def get_vendor_ids_from_order(order: Any) -> List[str]:
    """Return a deduplicated list of vendor_ids from all order items."""
    if not order or not hasattr(order, "items"):
        return []
    return list({item.vendor_id for item in (order.items or []) if item.vendor_id})


def format_shipping_address(order_details: Any) -> str:
    """Formats the shipping address from order details."""
    if not order_details:
        return ""
    parts = [
        order_details.shipping_apartment,
        order_details.shipping_address,
        order_details.shipping_city,
        order_details.shipping_state,
        order_details.shipping_country,
    ]
    address = ", ".join([p for p in parts if p])
    if order_details.shipping_postal_code:
        address += f", Postcode - {order_details.shipping_postal_code}"
    return address


def _safe_send_email(trigger: str, context: dict):
    """Internal helper to send email with error handling."""
    try:
        send_template_email(trigger=trigger, context_data=context)
    except Exception as e:
        logger.error(f"Failed to send email for trigger '{trigger}': {e}", exc_info=True)


def send_payment_confirmation_email(order: Any, amount: float):
    """Sends a payment confirmation email to the customer."""
    context = {
        "customer_id": order.user_id,
        "customer_email": getattr(order.order_details, "customer_email", None),
        "customer_name": getattr(order.order_details, "customer_name", "Customer"),
        "vendor_id": get_vendor_ids_from_order(order),
        "order_id": order.order_number,
        "shipping_address": format_shipping_address(order.order_details),
        "amount": amount,
        "currency": order.currency,
    }
    _safe_send_email("payment.confirmed", context)


def send_order_shipped_email(order: Any, items: List[Any] = None):
    """Sends an order shipped email with tracking information."""
    shipped_items = items if items is not None else (order.items or [])
    context = {
        "customer_id": order.user_id,
        "customer_email": getattr(order.order_details, "customer_email", None),
        "customer_name": getattr(order.order_details, "customer_name", "Customer"),
        "vendor_id": get_vendor_ids_from_order(order),
        "order_id": order.order_number,
        "tracking_number": order.tracking_number,
        "courier": order.courier,
        "courier_link": order.tracking_link,
        "items": [
            {"name": item.name, "quantity": item.quantity, "sku": item.sku}
            for item in shipped_items
        ],
    }
    _safe_send_email("order.shipped", context)


def send_order_delivered_email(order: Any):
    """Sends an order delivered email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
    }
    _safe_send_email("order_delivered", context)


def send_order_completed_email(order: Any):
    """Sends an order completed email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
    }
    _safe_send_email("order_completed", context)


def send_order_confirmed_email(order: Any):
    """Sends an order confirmation email (created)."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
    }
    _safe_send_email("order_created", context)


def send_order_cancelled_email(order: Any):
    """Sends an order cancellation email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": getattr(order.order_details, "customer_email", None),
        "customer_name": getattr(order.order_details, "customer_name", "Customer"),
        "order_number": order.order_number,
        "vendor_id": get_vendor_ids_from_order(order),
        "order_id": order.id,
        "order_status": order.status.value if hasattr(order.status, "value") else order.status,
        "order_items": [
            {"name": item.name, "quantity": item.quantity, "sku": item.sku}
            for item in (order.items or [])
        ],
    }
    _safe_send_email("order.cancelled", context)


def send_return_request_email(order: Any):
    """Sends a return request acknowledgment email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
        "reason": getattr(order, "return_reason", None),
    }
    _safe_send_email("return_request_received", context)


def send_replacement_request_email(order: Any):
    """Sends a replacement request acknowledgment email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
        "reason": getattr(order, "return_reason", None),
    }
    _safe_send_email("replacement_request_received", context)


def send_order_replaced_email(order: Any):
    """Sends an order replacement notification email."""
    context = {
        "customer_id": order.user_id,
        "customer_email": order.order_details.customer_email,
        "customer_name": order.order_details.customer_name,
        "order_number": order.order_number,
        "order_id": order.id,
    }
    _safe_send_email("order_replaced", context)


def send_tracking_updated_email(order: Any, items: List[Any] = None):
    """Sends an email when the tracking information is updated."""
    shipped_items = items if items is not None else (order.items or [])
    context = {
        "customer_id": order.user_id,
        "customer_email": getattr(order.order_details, "customer_email", None),
        "customer_name": getattr(order.order_details, "customer_name", "Customer"),
        "order_number": order.order_number,
        "order_id": order.id,
        "tracking_number": order.tracking_number,
        "courier": order.courier,
        "courier_link": order.tracking_link,
        "items": [
            {"name": item.name, "quantity": item.quantity, "sku": item.sku}
            for item in shipped_items
        ],
    }
    _safe_send_email("order.tracking_updated", context)
