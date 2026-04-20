# app/routers/orders.py
from loguru import logger
from fastapi import (
    HTTPException,
    status,
    Request,
)
from utils.gcp_bucket import upload_file_to_gcs
from models.orders import OrderTimelineEntry
from models.activity_log import OrderActivityLog
from fastapi.responses import StreamingResponse
from schemas.orders import (
    OrderOut,
    OrderStatusUpdate,
    OrderAddressUpdate,
)
from service.orders import (
    call_payment_refund,
    get_orders_without_pagination,
    export_orders_csv,
    get_orders_admin,
    handle_inventory,
    update_order_status_logic,
    log_activity,
    count_orders_admin,
    export_orders_report,
)
from models.orders import (
    Order,
    OrderStatus,
    PaymentStatus,
    OrderDetails,
    OrderItem,
    OrderItemTracking,
)
from models.shipping_partner import ShipmentPartner
from sqlalchemy import select, or_
from datetime import datetime
import io
import pandas as pd
from typing import Optional, Dict, Any
import uuid
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi.responses import FileResponse
from fastapi import Response
from service.email_service import (
    send_order_confirmed_email,
    send_order_shipped_email,
    send_order_delivered_email,
    send_order_cancelled_email,
    send_order_completed_email,
    send_return_request_email,
    send_replacement_request_email,
    send_order_replaced_email,
    send_tracking_updated_email,
)
from openpyxl.styles import Font, Alignment
from sqlalchemy import delete
from service.order_base_service import OrderBaseService

ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [
        OrderStatus.SHIPPED,
        OrderStatus.PARTIALLY_SHIPPED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.PARTIALLY_SHIPPED: [
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
    ],
    OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
    OrderStatus.DELIVERED: [
        OrderStatus.RETURN_REQUESTED,
        OrderStatus.REPLACEMENT_REQUESTED,
        OrderStatus.RETURNED,
        OrderStatus.COMPLETED,
    ],
    OrderStatus.RETURN_REQUESTED: [OrderStatus.RETURNED, OrderStatus.RETURN_REJECTED],
    OrderStatus.REPLACEMENT_REQUESTED: [
        OrderStatus.REPLACEMENT,
        OrderStatus.RETURNED,
        OrderStatus.REPLACEMENT_REJECTED,
    ],
    OrderStatus.RETURNED: [OrderStatus.REFUNDED, OrderStatus.REPLACEMENT],
    OrderStatus.REPLACEMENT: [],
    OrderStatus.CANCELLED: [OrderStatus.REFUNDED],
    OrderStatus.COMPLETED: [
        OrderStatus.RETURN_REQUESTED,
        OrderStatus.REPLACEMENT_REQUESTED,
    ],
}


def get_available_actions(order: Order) -> list[str]:
    actions = []

    # Forward transitions based on ALLOWED_TRANSITIONS
    if order.status == OrderStatus.PENDING:
        if order.payment_status != PaymentStatus.PENDING:
            actions.append("confirm")
    elif order.status == OrderStatus.CONFIRMED:
        actions.append("ship")
    elif order.status == OrderStatus.PARTIALLY_SHIPPED:
        actions.append("ship")
        actions.append("deliver")
    elif order.status == OrderStatus.SHIPPED:
        actions.append("deliver")

    # Check cancel availability
    if order.status not in [
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
        OrderStatus.REPLACEMENT,
        OrderStatus.RETURN_REQUESTED,
        OrderStatus.REPLACEMENT_REQUESTED,
        OrderStatus.RETURN_REJECTED,
        OrderStatus.REPLACEMENT_REJECTED,
    ]:
        actions.append("cancel")

    if order.tracking_link:
        actions.append("track")

    if order.status in [
        OrderStatus.DELIVERED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.RETURN_REQUESTED,
    ]:
        actions.append("return")
    if order.status in [
        OrderStatus.DELIVERED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REPLACEMENT_REQUESTED,
    ]:
        actions.append("replace")

    if order.status == OrderStatus.DELIVERED:
        actions.append("mark_completed")

    if order.status == OrderStatus.RETURN_REQUESTED:
        actions.append("reject_return")

    if order.status == OrderStatus.REPLACEMENT_REQUESTED:
        actions.append("reject_replacement")

    # Check refund availability
    if order.status in [
        OrderStatus.RETURNED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.CANCELLED,
        OrderStatus.DELIVERED,
        OrderStatus.PARTIALLY_REFUNDED,
    ]:
        if (order.refund_amount or 0.0) < (order.total_amount or 0.0):
            actions.append("refund")

    return actions


def get_admin_item_available_actions(order, item):
    actions = []
    if item.status == OrderStatus.CANCELLED:
        return actions

    if item.status == OrderStatus.SHIPPED:
        actions.append("delivered")

    if order.status in [OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_SHIPPED]:
        if item.status not in [OrderStatus.SHIPPED, OrderStatus.CANCELLED]:
            actions.append("ship")
    # Cancel availability
    if order.status not in [
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
        OrderStatus.CANCELLED,
        OrderStatus.REPLACEMENT,
    ]:
        actions.append("cancel")

    if order.status == OrderStatus.REPLACEMENT:
        actions.append("cancel")

    # Return/Replace availability
    if order.status in [OrderStatus.DELIVERED, OrderStatus.PARTIALLY_RETURNED]:
        if item.status != OrderStatus.RETURNED:
            actions.append("return")
            actions.append("replace")

    return actions


class OrderAdminService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)

    async def update_order_tags(self, order_id, tags):
        order = await self.get_order_or_404(order_id)
        order.tags = tags
        await self.db.commit()

        await log_activity(
            self.db,
            order.id,
            "Tags Updated",
            user_id="system",
            description="Order tags were updated",
        )

        await self.db.refresh(order)
        return order

    async def list_orders(self, request: Request, response: Response, params: Dict[str, Any]):
        """List orders for admin with filters and pagination"""
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}

        if params.get("download"):
            orders = await get_orders_without_pagination(self.db, params)
            file_path = await export_orders_csv(orders)
            return FileResponse(file_path, media_type="text/csv", filename="orders.csv")

        # Fetch data
        orders = await get_orders_admin(self.db, params)
        total = await count_orders_admin(self.db, params)

        for order in orders:
            order.available_actions = get_available_actions(order)
            for item in order.items:
                item.available_actions = get_admin_item_available_actions(order, item)

        return orders, total

    async def export_orders(self, params: Dict[str, Any], format: str = "excel"):
        """Export orders in Excel or CSV format"""
        df = await export_orders_report(self.db, params)

        # CSV
        if format == "csv":
            buffer = io.StringIO()
            df.to_csv(buffer, index=False)
            buffer.seek(0)
            return StreamingResponse(
                buffer,
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=orders_export.csv"},
            )

        # Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Orders", index=False, startrow=2)
            worksheet = writer.sheets["Orders"]

            headers = [
                ("Order Details", 1, 3),
                ("Customer Details Shipping details", 4, 15),
                ("Product Details", 16, 25),
                ("Vendor", 26, 26),
                ("Warehouse", 27, 27),
                ("Tracking Details", 28, 31),
                ("Order Status", 32, 33),
                ("Payment details", 34, 34),
                ("Customer Details Billing Details", 35, 44),
            ]

            for title, start, end in headers:
                worksheet.merge_cells(
                    start_row=1, start_column=start, end_row=1, end_column=end
                )
                cell = worksheet.cell(row=1, column=start)
                cell.value = title
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

            for cell in worksheet[2]:
                cell.font = Font(bold=True)

        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=orders_export.xlsx"},
        )

    async def get_order_details(self, order_id: str):
        """Get order details including status, items, and combined timeline"""
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.order_details),
                selectinload(Order.items).selectinload(OrderItem.tracking_details).selectinload(OrderItemTracking.courier_partner),
                selectinload(Order.courier_partner),
                selectinload(Order.returns),
            )
            .where(or_(Order.id == order_id, Order.order_number == order_id))
        )

        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Order not found")

        # Fetch Activity Logs
        logs_result = await self.db.execute(
            select(OrderActivityLog).where(OrderActivityLog.order_id == order.id)
        )
        logs = logs_result.scalars().all()

        combined_timeline = []
        # 1. Add custom notes (OrderTimelineEntry)
        if hasattr(order, "timeline") and order.timeline:
            for entry in order.timeline:
                combined_timeline.append(
                    {
                        "id": entry.id,
                        "text": entry.text,
                        "attachments": entry.attachments,
                        "user_id": entry.user_id,
                        "created_at": entry.created_at,
                        "type": "custom",
                    }
                )

        # 2. Add system logs (OrderActivityLog)
        for log in logs:
            combined_timeline.append(
                {
                    "id": log.id,
                    "text": f"{log.action}"
                    + (f": {log.description}" if log.description else ""),
                    "attachments": [],
                    "user_id": log.user_id or "SYSTEM",
                    "created_at": log.created_at,
                    "type": "system",
                }
            )

        # 3. Sort by created_at descending
        combined_timeline.sort(key=lambda x: x["created_at"], reverse=True)

        order.available_actions = get_available_actions(order)
        for i in order.items:
            i.available_actions = get_admin_item_available_actions(order, i)

        order_out = OrderOut.model_validate(order).model_dump()
        order_out["timeline"] = combined_timeline

        return order_out

    async def update_order_status(
        self, order_id: str, status_update: OrderStatusUpdate, user: dict
    ):
        """Update order status with validations and side effects (emails, inventory)"""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.order_details), selectinload(Order.items))
            .where(or_(Order.id == order_id, Order.order_number == order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Order not found")

        old_status = order.status
        try:
            new_status = OrderStatus(status_update.status.lower())
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status_update.status}")

        # Validate transition
        if order.status != new_status:
            allowed = ALLOWED_TRANSITIONS.get(order.status, [])
            if new_status not in allowed:
                raise HTTPException(
                    400,
                    f"Invalid status transition from {order.status.value} to {new_status.value}. "
                    f"Allowed transitions: {[s.value for s in allowed]}",
                )

        if (
            new_status == OrderStatus.CONFIRMED
            and order.payment_status == PaymentStatus.PENDING
        ):
            raise HTTPException(400, "Cannot confirm order with pending payment status.")

        # Update order status
        order.status = new_status

        # Update fields and track changes
        tracking_updated = False
        if status_update.tracking_number and status_update.tracking_number != order.tracking_number:
            order.tracking_number = status_update.tracking_number
            tracking_updated = True
        if status_update.courier and status_update.courier != order.courier:
            order.courier = status_update.courier
            tracking_updated = True
            
        if status_update.actual_delivery_date:
            order.actual_delivery_date = status_update.actual_delivery_date
        
        if status_update.courier_id:
            order.courier_id = status_update.courier_id
        elif status_update.courier and tracking_updated:
            try:
                cp_result = await self.db.execute(
                    select(ShipmentPartner).where(
                        ShipmentPartner.name.ilike(status_update.courier)
                    )
                )
                partner = cp_result.scalar_one_or_none()
                if partner:
                    order.courier_id = partner.id
            except Exception as e:
                logger.warning(f"Could not find courier partner {status_update.courier}: {e}")

        if tracking_updated or status_update.courier_id:
            for item in order.items:
                if item.status != OrderStatus.CANCELLED:
                    # Create tracking record for the item matching the order's new tracking info
                    tracking_record = OrderItemTracking(
                        order_item_id=item.id,
                        quantity_shipped=item.quantity,
                        tracking_number=status_update.tracking_number or order.tracking_number,
                        courier=status_update.courier or order.courier,
                        courier_id=status_update.courier_id or order.courier_id
                    )
                    self.db.add(tracking_record)

        if order.status == OrderStatus.DELIVERED and not order.actual_delivery_date:
            order.actual_delivery_date = datetime.now()

        if status_update.notes:
            order.notes = (
                status_update.notes
                if not order.notes
                else f"{order.notes}\n{status_update.notes}"
            )

        # Inventory Side Effects
        if new_status == OrderStatus.CANCELLED:
            try:
                await handle_inventory(
                    "release", order.items, warehouse_id=order.warehouse_id
                )
            except Exception as e:
                logger.error(f"Inventory release failed: {str(e)}")
                raise HTTPException(
                    400, "Inventory service failed while updating this order."
                )

        # Log Activity
        await log_activity(
            self.db,
            order.id,
            action=f"Status Update: {new_status.value}",
            status_from=old_status.value,
            status_to=new_status.value,
            description=status_update.notes,
            user_id=user.get("user_id") if user else "SYSTEM",
        )

        await self.db.commit()
        await self.db.refresh(order)

        # Email Side Effects
        email_map = {
            OrderStatus.CONFIRMED: send_order_confirmed_email,
            OrderStatus.SHIPPED: send_order_shipped_email,
            OrderStatus.DELIVERED: send_order_delivered_email,
            OrderStatus.CANCELLED: send_order_cancelled_email,
            OrderStatus.COMPLETED: send_order_completed_email,
            OrderStatus.RETURN_REQUESTED: send_return_request_email,
            OrderStatus.REPLACEMENT_REQUESTED: send_replacement_request_email,
            OrderStatus.REPLACEMENT: send_order_replaced_email,
        }

        # Email Side Effects
        try:
            if new_status == OrderStatus.SHIPPED and old_status != OrderStatus.SHIPPED:
                send_order_shipped_email(order)
            elif tracking_updated:
                send_tracking_updated_email(order)
            elif new_status in email_map and new_status != old_status:
                email_map[new_status](order)
        except Exception as e:
            logger.error(f"Failed to send email for status {new_status} or tracking update: {str(e)}")

        order.available_actions = get_available_actions(order)
        for i in order.items:
            i.available_actions = get_admin_item_available_actions(order, i)

        return order

    async def cancel_order_item(self, item_id: int, user: dict):
        """Cancel a single order item (Admin)"""
        # 1. Fetch the item
        item_result = await self.db.execute(select(OrderItem).where(OrderItem.id == item_id))
        item = item_result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail="Order Item not found")

        # 2. Fetch the parent order
        order_result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.order_details))
            .where(Order.id == item.order_id)
        )
        order = order_result.scalar_one_or_none()

        if not order:
            raise HTTPException(status_code=404, detail="Parent Order not found")

        # 3. Cancel the item
        if item.status == OrderStatus.CANCELLED:
            raise HTTPException(status_code=400, detail="Item is already cancelled")

        item.status = OrderStatus.CANCELLED

        # Release stock for this item
        await handle_inventory("release", [item], warehouse_id=order.warehouse_id)

        # 4. Update Parent Order Status if needed
        all_cancelled = True
        active_subtotal = 0.0

        for i in order.items:
            if i.status != OrderStatus.CANCELLED:
                all_cancelled = False
                active_subtotal += i.total_price or 0.0

        if all_cancelled:
            order.status = OrderStatus.CANCELLED

        # 5. Update Financials (if payment is still pending)
        if order.payment_status == PaymentStatus.PENDING:
            order.subtotal = active_subtotal
            order.total_amount = (
                active_subtotal
                + (order.shipping_cost or 0)
                + (order.tax_amount or 0)
                - (order.discount_amount or 0)
            )

        await log_activity(
            self.db,
            order.id,
            action="Item Cancelled (Admin)",
            user_id=user.get("user_id"),
            description=f"Item {item.id} (SKU: {item.sku}) cancelled by admin",
        )
        await self.db.commit()
        await self.db.refresh(order)

        order.available_actions = get_available_actions(order)
        for i in order.items:
            i.available_actions = get_admin_item_available_actions(order, i)
        return order

    async def ship_order_item(
        self,
        item_id: int,
        user: dict,
        tracking_number: Optional[str] = None,
        courier: Optional[str] = None,
        quantity: Optional[int] = None,
    ):
        """Mark a single order item as SHIPPED (Admin)"""
        # 1. Fetch Item & Order
        item_result = await self.db.execute(
            select(OrderItem)
            .options(selectinload(OrderItem.tracking_details))
            .where(OrderItem.id == item_id)
        )
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(404, "Order Item not found")

        order_result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.order_details))
            .where(Order.id == item.order_id)
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Parent Order not found")

        # 2. Validation
        if order.status not in [OrderStatus.CONFIRMED, OrderStatus.PARTIALLY_SHIPPED]:
            raise HTTPException(
                400, f"Cannot ship items for order in status {order.status.value}"
            )

        if item.status == OrderStatus.SHIPPED and quantity is None:
            raise HTTPException(400, "Item already fully shipped")

        if item.status == OrderStatus.CANCELLED:
            raise HTTPException(400, "Cannot ship a cancelled item")

        try:
            qty_to_ship = quantity if quantity is not None else item.quantity

            if tracking_number:
                tracking_record = OrderItemTracking(
                    order_item_id=item.id,
                    quantity_shipped=qty_to_ship,
                    tracking_number=tracking_number,
                    courier=courier
                )
                if courier:
                    try:
                        cp_result = await self.db.execute(
                            select(ShipmentPartner).where(
                                ShipmentPartner.name.ilike(courier)
                            )
                        )
                        partner = cp_result.scalar_one_or_none()
                        if partner:
                            tracking_record.courier_id = partner.id
                    except Exception as e:
                        logger.warning(f"Could not find courier partner {courier}: {e}")
                
                self.db.add(tracking_record)

            # Check if total shipped quantity >= item.quantity to mark item as fully SHIPPED
            total_shipped = sum(t.quantity_shipped for t in item.tracking_details) + qty_to_ship
            if total_shipped >= item.quantity:
                item.status = OrderStatus.SHIPPED
            else:
                item.status = OrderStatus.PARTIALLY_SHIPPED

            # 4. Determine Parent Order Status
            active_items = [i for i in order.items if i.status != OrderStatus.CANCELLED]
            all_shipped = all(i.status == OrderStatus.SHIPPED for i in active_items)

            new_order_status = (
                OrderStatus.SHIPPED if all_shipped else OrderStatus.PARTIALLY_SHIPPED
            )

            # 5. Update Order
            notes = f"Item {item.name} (SKU: {item.sku}) marked as Shipped."
            if tracking_number:
                notes += f" Tracking: {tracking_number}"

            await update_order_status_logic(
                self.db,
                order,
                new_order_status,
                user_id=user.get("user_id"),
                notes=notes,
                tracking_number=tracking_number,
                courier=courier,
                items=[item],
            )

            await self.db.commit()
            await self.db.refresh(order)
            order.available_actions = get_available_actions(order)
            for i in order.items:
                i.available_actions = get_admin_item_available_actions(order, i)
            return order

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Item shipping failed: {str(e)}")

    async def cancel_order(self, order_id: str, user: dict, reason: str):
        """Cancel an entire order (Admin)"""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.order_details))
            .where(or_(Order.id == order_id, Order.order_number == order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Order not found")

        if order.status in [
            OrderStatus.CANCELLED,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
            OrderStatus.COMPLETED,
        ]:
            raise HTTPException(
                400, f"Order cannot be cancelled in current status: {order.status.value}"
            )

        try:
            old_status = order.status
            order.status = OrderStatus.CANCELLED
            order.cancellation_reason = reason

            for item in order.items:
                if item.status != OrderStatus.CANCELLED:
                    item.status = OrderStatus.CANCELLED

            # Release inventory
            await handle_inventory("release", order.items, warehouse_id=order.warehouse_id)

            await log_activity(
                self.db,
                order.id,
                action="Order Cancelled (Admin)",
                user_id=user.get("user_id"),
                status_from=old_status.value,
                status_to=OrderStatus.CANCELLED.value,
                description=f"Cancelled by Admin. Reason: {reason}",
            )

            await self.db.commit()
            await self.db.refresh(order)

            # Email notification
            try:
                send_order_cancelled_email(order)
            except Exception as e:
                logger.error(f"Failed to send cancellation email: {str(e)}")

            order.available_actions = get_available_actions(order)
            for i in order.items:
                i.available_actions = get_admin_item_available_actions(order, i)
            return order

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Order cancellation failed: {str(e)}")

    async def process_refund(self, order_id: str, user: dict, amount: float, reason: str):
        """Process refund for an order (Admin)"""
        if amount <= 0:
            raise HTTPException(400, "Refund amount must be greater than zero")

        user_id = user.get("user_id")
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.order_details))
            .where(or_(Order.id == order_id, Order.order_number == order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(404, "Order not found")

        if order.status not in [
            OrderStatus.RETURNED,
            OrderStatus.CANCELLED,
            OrderStatus.DELIVERED,
            OrderStatus.PARTIALLY_REFUNDED,
        ]:
            raise HTTPException(400, f"Cannot refund order in status {order.status.value}")

        try:
            current_refund = float(order.refund_amount or 0.0)
            new_refund_total = current_refund + amount

            # Validation: cannot refund more than paid/total
            if new_refund_total > float(order.total_amount or 0.0):
                raise HTTPException(
                    400,
                    f"Refund amount exceeds order total. Max available: {float(order.total_amount) - current_refund}",
                )

            # Generate idempotency key
            idempotency_key = f"ref_ord_{order.id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

            # Call payment service for refund
            payment_payload = {
                "order_id": order.id,
                "amount": amount,
                "currency": order.currency or "INR",
                "reason": reason,
            }
            await call_payment_refund(payment_payload, idempotency_key=idempotency_key)

            # Update refund amount
            order.refund_amount = new_refund_total

            # Determine status
            if new_refund_total < float(order.total_amount or 0.0):
                new_status = OrderStatus.PARTIALLY_REFUNDED
                new_payment_status = PaymentStatus.PARTIALLY_REFUNDED
            else:
                new_status = OrderStatus.REFUNDED
                new_payment_status = PaymentStatus.REFUNDED

            order.payment_status = new_payment_status
            await update_order_status_logic(
                self.db,
                order,
                new_status,
                user_id=user_id,
                notes=f"Refunded {amount}. Reason: {reason}",
            )
            await self.db.commit()
            await self.db.refresh(order)
            order.available_actions = get_available_actions(order)
            return order
        except HTTPException as he:
            raise he
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Refund failed: {str(e)}")
            raise HTTPException(400, f"Refund failed: {str(e)}")

    async def delete_order(self, order_id: str):
        """Delete a single order and its components"""
        order = await self.get_order_or_404(order_id)
        try:
            # Delete OrderItems
            await self.db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
            # Delete OrderDetails
            await self.db.execute(delete(OrderDetails).where(OrderDetails.order_id == order.id))
            # Delete OrderTimeline entries if any
            await self.db.execute(delete(OrderTimelineEntry).where(OrderTimelineEntry.order_id == order.id))
            # Finally delete the Order
            await self.db.delete(order)
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, f"Failed to delete order: {str(e)}")

    async def delete_all_orders(self):
        """Delete ALL orders (Admin)"""
        try:
            await self.db.execute(delete(OrderItem))
            await self.db.execute(delete(OrderDetails))
            await self.db.execute(delete(OrderTimelineEntry))
            await self.db.execute(delete(Order))
            await self.db.commit()
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, f"Failed to delete all orders: {str(e)}")

    async def update_payment_status_system(self, order_id: str, payment_status: str):
        """System-only method to update payment status with side effects."""
        order = await self.get_order_or_404(order_id)
        try:
            try:
                new_payment_status = PaymentStatus(payment_status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid payment status. Allowed: {[s.value for s in PaymentStatus]}",
                )

            old_payment_status = order.payment_status

            if old_payment_status == PaymentStatus.PAID and new_payment_status == PaymentStatus.PENDING:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot revert payment status from PAID to PENDING",
                )

            order.payment_status = new_payment_status

            if new_payment_status == PaymentStatus.PAID:
                if order.status == OrderStatus.PENDING:
                    await update_order_status_logic(
                        db=self.db,
                        order=order,
                        new_status=OrderStatus.CONFIRMED,
                        user_id="SYSTEM",
                        notes="Payment Confirmed via System API",
                    )
                    from service.email_service import send_payment_confirmation_email
                    try:
                        send_payment_confirmation_email(order, order.total_amount)
                    except Exception as e:
                        logger.error(f"Failed to send payment email: {e}")

                for item in order.items:
                    if item.status == OrderStatus.PENDING:
                        item.status = order.status

            await log_activity(
                self.db,
                order.id,
                "Payment Status Updated (System)",
                user_id="SYSTEM",
                description=f"Payment status changed from {old_payment_status} to {new_payment_status.value}",
            )

            await self.db.commit()
            await self.db.refresh(order)

            order.available_actions = get_available_actions(order)
            for i in order.items:
                i.available_actions = get_admin_item_available_actions(order, i)

            return order
        except HTTPException as he:
            raise he
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=400, detail=f"Failed to update payment status: {str(e)}")

    async def update_order_address(
        self, order_id: str, payload: OrderAddressUpdate, user_id: str
    ):
        """Update order shipping/billing address"""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.order_details))
            .where(or_(Order.id == order_id, Order.order_number == order_id))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Order not found")

        from service.orders import update_order_address as update_addr_logic

        await update_addr_logic(
            self.db,
            order,
            payload.shipping,
            payload.billing,
            user_id,
        )
        await self.db.commit()
        await self.db.refresh(order)
        return order

    async def delete_order_item(self, item_id: int):
        """Delete a single order item (Admin)"""
        item_result = await self.db.execute(select(OrderItem).where(OrderItem.id == item_id))
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(404, "Order Item not found")

        order_id = item.order_id
        try:
            await self.db.delete(item)
            await self.db.commit()

            # Refresh order to reflect changes
            result = await self.db.execute(
                select(Order)
                .options(selectinload(Order.items), selectinload(Order.order_details))
                .where(Order.id == order_id)
            )
            order = result.scalar_one()
            order.available_actions = get_available_actions(order)
            for i in order.items:
                i.available_actions = get_admin_item_available_actions(order, i)
            return order
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, f"Failed to delete order item: {str(e)}")


class OrderTimelineService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)

    def get_order_timeline(self, order_id):
        order = self.get_order_or_404(order_id)
        return order.timeline

    async def add_order_timeline(
        self, order_id, text, attachments=None, user=None, files=None
    ):
        await self.get_order_or_404(order_id)

        if files:
            for file in files:
                if file.filename:  # check if file was actually uploaded
                    content = await file.read()
                    # Generate unique blob name
                    blob_name = (
                        f"order_timeline/{order_id}/{uuid.uuid4()}_{file.filename}"
                    )
                    content_type = file.content_type or "application/octet-stream"

                    try:
                        url = upload_file_to_gcs(content, content_type, blob_name)
                        attachments.append(
                            {"url": url, "name": file.filename, "size": len(content)}
                        )
                    except Exception as e:
                        raise HTTPException(
                            502, f"Failed to upload {file.filename}: {str(e)}"
                        )

        # 2. Save to DB
        new_entry = OrderTimelineEntry(
            order_id=order_id,
            text=text,
            attachments=attachments,
            user_id=user.get("user_id") if user else None,
        )
        self.db.add(new_entry)
        await self.db.commit()
        await self.db.refresh(new_entry)
