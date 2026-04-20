from service.order_base_service import OrderBaseService
from models.orders import OrderStatus, Order
from utils.session import get_or_create_session_token
from loguru import logger
from models.orders import (
    PaymentStatus,
    OrderDetails,
    OrderItem,
    OrderDiscount,
    OrderItemDiscount,
    generate_order_number,
)
from models.shipping_partner import ShipmentPartner
from models.order_number_config import OrderNumberConfig
from sqlalchemy import select
from datetime import datetime
import datetime
from fastapi import HTTPException
from typing import Dict, Any
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi.responses import FileResponse
from service.shipstation_service import (
    convert_to_shipstation_format,
)
from service.aramex_service import AramexService
from utils.api_calling import call_product_service_add_review
from dotenv import load_dotenv
import os
from service.orders import update_order_status_logic
from models.orders import OrderReturn, ReturnStatus, OrderReturnItem
from fastapi import status
from service.orders import (
    get_orders,
    count_orders,
    call_payment_service,
    get_orders_without_pagination,
    export_orders_csv,
    log_activity,
    handle_inventory,
)
from service.email_service import (
    send_payment_confirmation_email,
)

load_dotenv()

PRODUCT_BASE_URL = os.getenv(
    "PRODUCT_URL",
    "https://shopper-beats-products-877627218975.australia-southeast2.run.app",
)


def get_item_available_actions(order, item):
    actions = []
    if item.status == OrderStatus.CANCELLED:
        return actions

    if order.status in [
        OrderStatus.PENDING,
        OrderStatus.UNSHIPPED,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
    ]:
        actions.append("cancel")

    if order.status in [
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.PARTIALLY_REFUNDED,
    ]:
        if item.status != OrderStatus.RETURNED:
            actions.append("return")
            actions.append("replace")
        actions.append("review")
    return actions


def get_customer_available_actions(order):
    actions = []

    # Cancel availability (customer can cancel before shipment)
    if order.status in [
        OrderStatus.PENDING,
        OrderStatus.UNSHIPPED,
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
    ]:
        actions.append("cancel")

    if order.tracking_link:
        actions.append("track")

    # Return/Replace/Review availability
    if order.status in [
        OrderStatus.DELIVERED,
        OrderStatus.COMPLETED,
        OrderStatus.PARTIALLY_RETURNED,
        OrderStatus.PARTIALLY_REFUNDED,
    ]:
        actions.append("return")
        actions.append("replace")
        actions.append("review")
    return actions


class OrderService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)

    async def get_order(self, order_id, includes=None, filters=None, user_id=None):
        if user_id:
            filters = (filters or []) + [Order.user_id == user_id]
        order = await self.get_order_or_404(order_id, includes=includes, filters=filters)
        order.available_actions = get_customer_available_actions(order)
        for item in order.items:
            item.available_actions = get_item_available_actions(order, item)
        return order

    async def generate_order_number(self):
        base_number = generate_order_number()

        config_result = await self.db.execute(
            select(OrderNumberConfig).where(OrderNumberConfig.is_active == True)
        )
        config = config_result.scalars().first()

        prefix = config.prefix if config and config.prefix else ""
        suffix = config.suffix if config and config.suffix else ""
        final_order_number = f"{prefix}{base_number}{suffix}"
        return final_order_number

    async def create_order(self, order, user_id=None, request=None, response=None):
        order_data = order.model_dump(exclude_unset=True)
        logger.info(order_data)
        # Determine Order Status based on Payment Method
        payment_method_type = order.payment_method.type.lower()
        logger.info(payment_method_type)
        is_cod = payment_method_type == "cod"
        logger.info(is_cod)

        # COD orders are ready to ship immediately (pending verification usually, but for this logic: Unshipped)
        # Online payments start as Pending until payment is confirmed
        initial_status = OrderStatus.UNSHIPPED if is_cod else OrderStatus.PENDING
        logger.info(initial_status)

        # Determine Order Number with Prefix/Suffix
        final_order_number = await self.generate_order_number()

        courier_name = order_data.get("courier")
        courier_id = None
        if courier_name:
            cp_result = await self.db.execute(
                select(ShipmentPartner).where(ShipmentPartner.name.ilike(courier_name))
            )
            partner = cp_result.scalar_one_or_none()
            if partner:
                courier_id = partner.id

        # 1. Prepare flat order fields (only those listed in Order model)
        # Exclude relationship fields and extra schema fields
        excluded_fields = {
            "items",
            "promotions",
            "shipping",
            "billing",
            "payment_method",
            "shipping_same_as_billing",
            "customer_name",
            "customer_email",
            "customer_phone",
            "shipping_details",
            "courier",
        }

        flat_order_data = {
            k: v for k, v in order_data.items() if k not in excluded_fields
        }

        # Create order in local database
        new_order = Order(
            order_number=final_order_number,
            courier=courier_name,
            courier_id=courier_id,
            status=initial_status,
            payment_status=PaymentStatus.PENDING,
            **flat_order_data,
        )
        logger.info(f"new_order: {new_order}")
        self.db.add(new_order)
        await self.db.flush()
        logger.info(f"new_order_id: {new_order.id}")

        # Determine billing
        billing = order.shipping if order.shipping_same_as_billing else order.billing
        logger.info(f"billing: {billing}")

        # Create snapshot
        snapshot = {
            "products": order_data.get("items"),
            "shipping_address": order.shipping.model_dump(),
            "billing_address": billing.model_dump(),
            "payment_method": order.payment_method.model_dump(),
            "customer": {
                "name": order_data.get("customer_name"),
                "email": order_data.get("customer_email"),
                "phone": order_data.get("customer_phone"),
            },
            "warehouse_id": order_data.get("warehouse_id"),
            "supplier_id": order_data.get("supplier_id"),
        }
        logger.info(f"snapshot: {snapshot}")

        # Create OrderDetails (your existing code)
        details = OrderDetails(
            order_id=new_order.id,
            customer_name=order.customer_name or order_data.get("customer_name"),
            customer_email=order.customer_email or order_data.get("customer_email"),
            customer_phone=order.customer_phone or order_data.get("customer_phone"),
            # Shipping
            shipping_first_name=order.shipping.first_name,
            shipping_last_name=order.shipping.last_name,
            shipping_company=order.shipping.company,
            shipping_address=order.shipping.address,
            shipping_apartment=order.shipping.apartment,
            shipping_city=order.shipping.city,
            shipping_state=order.shipping.state,
            shipping_country=order.shipping.country,
            shipping_postal_code=order.shipping.postal_code,
            shipping_phone=order.shipping.phone,
            shipping_house_no=order.shipping.house_no,
            landmark=order.shipping.landmark,
            # Billing
            billing_first_name=billing.first_name,
            billing_last_name=billing.last_name,
            billing_company=billing.company,
            billing_address=billing.address,
            billing_apartment=billing.apartment,
            billing_city=billing.city,
            billing_state=billing.state,
            billing_country=billing.country,
            billing_postal_code=billing.postal_code,
            billing_phone=billing.phone,
            billing_house_no=billing.house_no,
            customer_snapshot=snapshot,
        )

        self.db.add(details)
        await self.db.flush()
        await self.db.refresh(new_order)
        await self.db.refresh(details)

        # Create Order Discounts/Promotions
        if order.promotions:
            for promo in order.promotions:
                order_discount = OrderDiscount(
                    order_id=new_order.id,
                    promotion_code=promo.promotion_code,
                    promotion_type=promo.promotion_type,
                    amount=promo.amount,
                    description=promo.description,
                )
                self.db.add(order_discount)
            await self.db.flush()

        # Create OrderItems
        for item in order_data.get("items", []):
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=item.get("product_id"),
                name=item.get("name", "Unknown Product"),
                sku=item.get("sku"),
                quantity=item.get("quantity", 1),
                unit_price=item.get("unit_price", 0.0),
                total_price=item.get("total_price", 0.0),
                vendor_id=item.get("vendor_id"),
                status=initial_status,
            )

            # Handle Item Promotions
            item_promotions = item.get("promotions", [])
            for promo in item_promotions:
                item_discount = OrderItemDiscount(
                    promotion_code=promo.get("promotion_code"),
                    promotion_type=promo.get("promotion_type"),
                    amount=promo.get("amount", 0.0),
                )
                order_item.discounts.append(item_discount)

            self.db.add(order_item)
        await self.db.flush()

        # ShipStation Sync: Only execute if status is UNSHIPPED (e.g. COD)
        if initial_status == OrderStatus.UNSHIPPED:
            try:
                shipstation_order_data = await convert_to_shipstation_format(
                    new_order, details, order_data
                )

                shipstation_response = await shipstation_service.create_order(
                    shipstation_order_data
                )

                # Update local order with ShipStation IDs
                new_order.shipstation_order_id = shipstation_response.get("orderId")
                new_order.shipstation_order_key = shipstation_response.get("orderKey")
                new_order.shipstation_order_status = OrderStatus.UNSHIPPED

            except Exception as e:
                # Log error but don't fail the order creation?
                # Or strictly fail? Code previously failed.
                # Since it's COD, failing might be safer so we don't have "lost" orders.
                await self.db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to sync COD order to ShipStation: {str(e)}",
                )

        if user_id:
            print("###USER ID", user_id)
            new_order.user_id = user_id
        else:
            order_token = get_or_create_session_token(request, response)
            print("###ORDER TOKEN", order_token)
            new_order.session_token = order_token

        payment_response = {}
        # Call Payment Service for non-COD orders
        if not is_cod:

            try:
                payment_payload = {
                    "order_id": new_order.id,
                    "amount": int(new_order.total_amount),
                    "provider": order.payment_method.provider,
                    "currency": new_order.currency,
                    "customer": {
                        "user_id": new_order.user_id,
                        "guest_id": new_order.session_token,
                    },
                    # "promotions": [p.model_dump() for p in order.promotions] if order.promotions else [],
                    # "discount_amount": float(new_order.discount_amount or 0.0),
                }
                print("------", payment_payload, "payment_payload-----------------")
                logger.info(f"Initiating payment for order {new_order.id}")

                payment_response = await call_payment_service(payment_payload)
                print("payment------", payment_response)
            except Exception as e:
                logger.error(f"Payment failed: {str(e)}")
                await self.db.rollback()
                raise HTTPException(
                    status_code=400, detail=f"Payment initiation failed: {str(e)}"
                )

        # Lock Inventory
        await self.db.refresh(new_order, attribute_names=["items"])
        await handle_inventory(
            "lock", new_order.items, warehouse_id=new_order.warehouse_id
        )

        # Log Creation
        await log_activity(
            self.db,
            new_order.id,
            "Order Created",
            user_id=user_id,
            status_to=initial_status.value,
        )

        await self.db.commit()

        # Return the complete order
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.order_details),
                selectinload(Order.items),
            )
            .where(Order.id == new_order.id)
        )
        full_order = result.scalar_one()
        print(payment_response, "payment_response")

        # Send Payment Confirmation Email
        if not is_cod and payment_response.get("status") == "success":
            try:
                send_payment_confirmation_email(full_order, full_order.total_amount)
            except Exception as e:
                logger.error(f"Failed to send payment email: {e}")

        final_response = {
            "order_id": str(new_order.id),
            "order_number": new_order.order_number,
            "shipping_cost": float(new_order.shipping_cost or 0),
            **payment_response,
        }
        return final_response

    async def update_order_status(
        self, order_id, user, status_update, shipstation_service
    ):
        try:
            # Use centralized logic
            user_id = user.get("user_id") if user else None
            order = await self.get_order(order_id)
            updated_order = await update_order_status_logic(
                db=self.db,
                order=order,
                new_status=OrderStatus(status_update.status),
                user_id=user_id,
                notes=status_update.notes,
                tracking_number=(
                    status_update.tracking_number
                    if hasattr(status_update, "tracking_number")
                    else None
                ),  # tracking might be needed in request body?
            )
            logger.info("###UPDATED ORDER", updated_order)
            # Note: OrderStatusUpdate schema assumes simple updates.
            # Detailed updates (tracking etc) might need more fields in schema or logic adjustments.
            # For now, we map basics.

            await self.db.commit()
            await self.db.refresh(updated_order)
            logger.info("###UPDATED ORDER", updated_order)
            # ShipStation Sync if status became UNSHIPPED
            if (
                updated_order.status == OrderStatus.UNSHIPPED
                and not updated_order.shipstation_order_id
            ):
                logger.info("###UNSHIPPED")
                try:
                    # Convert options need loaded details (ensured by query update)
                    shipstation_order_data = await convert_to_shipstation_format(
                        updated_order, updated_order.order_details, {}
                    )
                    shipstation_response = await shipstation_service.create_order(
                        shipstation_order_data
                    )
                    updated_order.shipstation_order_id = shipstation_response.get(
                        "orderId"
                    )
                    updated_order.shipstation_order_key = shipstation_response.get(
                        "orderKey"
                    )
                    updated_order.shipstation_order_status = OrderStatus.UNSHIPPED

                    updated_order.notes = (
                        (updated_order.notes or "")
                        + f"\nSynced to ShipStation: {updated_order.shipstation_order_id}"
                    )

                    await self.db.commit()
                    await self.db.refresh(updated_order)
                    logger.info("###UPDATED ORDER", updated_order)
                    return updated_order
                except Exception as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Status updated but failed to push to ShipStation: {str(e)}",
                    )
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to update order status: {str(e)}",
            )

    async def update_payment_status(self, order_id, payload):
        order = await self.get_order(order_id)
        try:
            old_payment_status = order.payment_status
            order.payment_status = PaymentStatus(payload.payment_status)
            if payload.notes:
                order.notes = (
                    order.notes or ""
                ) + f"\n[{datetime.datetime.now()}] Payment Update: {payload.notes}"
            if (
                old_payment_status != PaymentStatus.PAID
                and order.payment_status == PaymentStatus.PAID
                and order.status == OrderStatus.PENDING
            ):
                # If order was PENDING and just got PAID, move to CONFIRMED
                # (assuming standard flow where Paid -> Confirmed -> Shipped)
                await update_order_status_logic(
                    self.db,
                    order,
                    OrderStatus.CONFIRMED,
                    notes="Auto-update: Payment Confirmed",
                )
            await log_activity(
                self.db,
                order.id,
                "Payment Update",
                status_from=old_payment_status.value,
                status_to=order.payment_status.value,
                description=(
                    f"Transaction ID: {payload.transaction_id}"
                    if payload.transaction_id
                    else None
                ),
            )
            await self.db.commit()
            await self.db.refresh(order)
            # Send Payment Confirmation Email if transitioned to PAID
            if (
                old_payment_status != PaymentStatus.PAID
                and order.payment_status == PaymentStatus.PAID
            ):
                logger.info("###SENDING PAYMENT EMAIL")
                try:
                    send_payment_confirmation_email(order, order.total_amount)
                    logger.info("-----Payment email sent-----")
                except Exception as e:
                    logger.error(f"-----Failed to send payment email: {e}-----")
            return order
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to update payment status: {str(e)}",
            )

    async def return_order(self, order_id, payload, user):
        print("order_id", order_id)
        order = await self.get_order(order_id)
        if order.status not in [OrderStatus.DELIVERED, OrderStatus.COMPLETED]:
            raise HTTPException(400, "Only delivered orders can be returned")

        # Check if return already exists
        existing_return = await self.db.execute(
            select(OrderReturn).where(OrderReturn.order_id == order.id)
        )
        if existing_return.scalar_one_or_none():
            raise HTTPException(400, "Return already requested for this order")
        print("existing_return", existing_return)
        try:
            # Create OrderReturn
            return_data = {
                "order_id": order.id,
                # "user_id": user_id,
                "status": ReturnStatus.REQUESTED,
                "return_type": payload.return_type,
                "reason": payload.reason,
                "customer_comment": payload.customer_comment,
            }

            # Add return address if provided
            if payload.return_address:
                return_data.update(
                    {
                        "return_first_name": payload.return_address.first_name,
                        "return_last_name": payload.return_address.last_name,
                        "return_company": payload.return_address.company,
                        "return_address": payload.return_address.address,
                        "return_apartment": payload.return_address.apartment,
                        "return_city": payload.return_address.city,
                        "return_state": payload.return_address.state,
                        "return_country": payload.return_address.country,
                        "return_postal_code": payload.return_address.postal_code,
                        "return_phone": payload.return_address.phone,
                        "return_house_no": payload.return_address.house_no,
                        "return_landmark": payload.return_address.landmark,
                    }
                )
            print("return_data", return_data)
            new_return = OrderReturn(**return_data)
            self.db.add(new_return)
            await self.db.flush()
            print("new_return", new_return)
            # Create OrderReturnItems for all items
            for item in order.items:
                return_item = OrderReturnItem(
                    return_id=new_return.id,
                    order_item_id=item.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    reason=payload.reason,  # Same reason for all if full order return
                    vendor_id=item.vendor_id,
                )
                self.db.add(return_item)

            # Determine new order status
            new_status = (
                OrderStatus.REPLACEMENT_REQUESTED
                if payload.return_type == "replacement"
                else OrderStatus.RETURN_REQUESTED
            )
            print("new_status", new_status)
            # update order status to indicate return requested
            await update_order_status_logic(
                self.db,
                order,
                new_status,
                notes=f"Customer requested {payload.return_type}. Reason: {payload.reason}",
            )
            print("new_status0", new_status)
            await self.db.commit()
            print("new_status1", new_status)
            await self.db.refresh(new_return)
            print("new_return", new_return)
            # Load items and relationships for response
            result = await self.db.execute(
                select(OrderReturn)
                .options(
                    selectinload(OrderReturn.items),
                    selectinload(OrderReturn.order).selectinload(Order.order_details),
                )
                .where(OrderReturn.id == new_return.id)
            )
            return result.scalar_one()
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Return request failed: {str(e)}")

    async def return_order_item(self, item_id, payload, user):
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        # 1. Fetch Item
        item_result = await self.db.execute(
            select(OrderItem).where(OrderItem.id == item_id)
        )
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(404, "Order Item not found")

        # 2. Fetch Order and Verify Ownership
        order_result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.order_details))
            .where(Order.id == item.order_id, Order.user_id == user_id)
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Parent Order not found or unauthorized")

        # 3. Validation
        if order.status not in [
            OrderStatus.DELIVERED,
            OrderStatus.COMPLETED,
            OrderStatus.PARTIALLY_RETURNED,
        ]:
            raise HTTPException(400, "Order must be Delivered to initiate return")

        if item.status == OrderStatus.RETURNED:
            raise HTTPException(400, "Item already returned")

        # Check for existing return request for this item
        existing_req_result = await self.db.execute(
            select(OrderReturn)
            .join(OrderReturnItem, OrderReturnItem.return_id == OrderReturn.id)
            .where(
                OrderReturnItem.order_item_id == item_id,
                OrderReturn.status != ReturnStatus.REJECTED,
            )
        )
        if existing_req_result.scalar_one_or_none():
            raise HTTPException(400, "Return request already exists for this item")

        try:
            # Create OrderReturn
            return_data = {
                "order_id": order.id,
                "user_id": user_id,
                "status": ReturnStatus.REQUESTED,
                "return_type": payload.return_type,
                "reason": payload.reason,
                "customer_comment": payload.customer_comment,
            }

            # Add return address if provided
            if payload.return_address:
                return_data.update(
                    {
                        "return_first_name": payload.return_address.first_name,
                        "return_last_name": payload.return_address.last_name,
                        "return_company": payload.return_address.company,
                        "return_address": payload.return_address.address,
                        "return_apartment": payload.return_address.apartment,
                        "return_city": payload.return_address.city,
                        "return_state": payload.return_address.state,
                        "return_country": payload.return_address.country,
                        "return_postal_code": payload.return_address.postal_code,
                        "return_phone": payload.return_address.phone,
                        "return_house_no": payload.return_address.house_no,
                        "return_landmark": payload.return_address.landmark,
                    }
                )

            new_return = OrderReturn(**return_data)
            self.db.add(new_return)
            await self.db.flush()

            # Create OrderReturnItem
            return_item = OrderReturnItem(
                return_id=new_return.id,
                order_item_id=item.id,
                product_id=item.product_id,
                quantity=item.quantity,
                reason=payload.reason,
                vendor_id=item.vendor_id,
            )
            self.db.add(return_item)

            # Update Item and Order Statuses
            item.status = OrderStatus.RETURNED
            all_returned = all(i.status == OrderStatus.RETURNED for i in order.items)
            new_order_status = (
                OrderStatus.RETURNED if all_returned else OrderStatus.PARTIALLY_RETURNED
            )

            if order.status != new_order_status:
                await update_order_status_logic(
                    self.db,
                    order,
                    new_order_status,
                    user_id=user_id,
                    notes=f"Item Return Requested. Reason: {payload.reason}",
                )

            await log_activity(
                self.db,
                order.id,
                action="Item Return Requested",
                user_id=user_id,
                description=f"Customer requested return for item {item.id} (SKU: {item.sku}). Reason: {payload.reason}",
            )

            await self.db.commit()
            await self.db.refresh(new_return)

            # Load items and relationships for response
            result = await self.db.execute(
                select(OrderReturn)
                .options(
                    selectinload(OrderReturn.items),
                    selectinload(OrderReturn.order).selectinload(Order.order_details),
                )
                .where(OrderReturn.id == new_return.id)
            )
            return result.scalar_one()

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Item Return failed: {str(e)}")

    async def cancel_order(self, order_id, user_id, reason):
        order = await self.get_order(order_id, user_id=user_id)

        if not order:
            raise HTTPException(404, "Order not found")

        if order.status in [
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED,
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
        ]:
            raise HTTPException(
                400, f"Cannot cancel order in status {order.status.value}"
            )

        try:
            await update_order_status_logic(
                self.db,
                order,
                OrderStatus.CANCELLED,
                user_id=user_id,
                notes=f"Cancellation Reason: {reason}",
            )
            await self.db.commit()
            await self.db.refresh(order)
            order.available_actions = get_customer_available_actions(order)
            return order
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Cancellation failed: {str(e)}")

    async def cancel_order_item(self, item_id, user):
        """
        Cancel a single order item.
        If all items in the order are cancelled, the main order status updates to CANCELLED.
        """
        print("STARTING-----", item_id)
        # 1. Fetch the item
        item_result = await self.db.execute(
            select(OrderItem).where(OrderItem.id == item_id)
        )
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

        if item.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            raise HTTPException(
                status_code=400, detail="Cannot cancel shipped/delivered item"
            )

        item.status = OrderStatus.CANCELLED

        # Release stock for this item
        await handle_inventory("release", [item], warehouse_id=order.warehouse_id)

        # 4. Update Parent Order Status if needed
        # Check if all items are now cancelled
        # Note: verify that order.items reflects the change to 'item'
        # Since they are in the same session, they should.

        all_cancelled = True
        active_subtotal = 0.0

        for i in order.items:
            # If 'i' is the same instance as 'item', its status is already updated in memory?
            # To be safe, we check if i.id == item.id, assume it's cancelled
            current_status = OrderStatus.CANCELLED if i.id == item.id else i.status

            if current_status != OrderStatus.CANCELLED:
                all_cancelled = False
                active_subtotal += i.total_price or 0.0

        if all_cancelled:
            order.status = OrderStatus.CANCELLED

        # Log item cancellation
        await log_activity(
            self.db,
            order.id,
            action="Item Cancelled",
            user_id=user.get("user_id") if user else None,
            description=f"Item {item.id} (SKU: {item.sku}) cancelled by customer",
        )

        # 5. Update Financials (if payment is still pending)
        if order.payment_status == PaymentStatus.PENDING:
            order.subtotal = active_subtotal
            # Recalculate total with simple logic: subtotal + shipping + tax - discount
            # Note: Shipping/tax might need re-calculation based on rules, sticking to simple update
            order.total_amount = (
                active_subtotal
                + (order.shipping_cost or 0)
                + (order.tax_amount or 0)
                - (order.discount_amount or 0)
            )

        await self.db.commit()
        await self.db.refresh(order)
        order.available_actions = get_customer_available_actions(order)

    async def list_orders(self, request, user, filters):
        params: Dict[str, Any] = {
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "status": filters.status,
            "payment_status": "paid",
            "warehouse_id": filters.warehouse_id,
            "courier": filters.courier,
            "supplier_id": filters.supplier_id,
            "brand": filters.brand,
            "min_total": filters.min_total,
            "max_total": filters.max_total,
            "q": filters.q,
            "sort_by": filters.sorting.sort_by,
            "sort_dir": filters.sorting.sort_dir,
            "page": filters.pagination.page,
            "per_page": filters.pagination.per_page,
        }
        #  Remove None values so build_order_filters works cleanly
        user_id = user.get("user_id", None)
        session_token = request.cookies.get("order_token")
        if not user_id and not session_token:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized, User id or session token is required",
            )
        params = {k: v for k, v in params.items() if v is not None}

        if filters.download:
            orders = await get_orders_without_pagination(self.db, params)
            file_path = await export_orders_csv(orders)
            return FileResponse(file_path, media_type="text/csv", filename="orders.csv")

        # Fetch data
        orders = await get_orders(self.db, params, user_id, session_token)
        total = await count_orders(self.db, params, user_id, session_token)

        for order in orders:
            order.available_actions = get_customer_available_actions(order)
            for item in order.items:
                item.available_actions = get_item_available_actions(order, item)
        return orders, total

    async def get_order_tracking_details(self, order_id, user):
        """Fetch live tracking details for Aramex/Fastway orders"""
        user_id = user.get("user_id", None)
        order = await self.get_order(
            order_id,
            includes=["order_details", "items", "courier_partner"],
            user_id=user_id,
        )

        # Check Courier
        courier = (order.courier or "").lower()
        if courier not in ["aramex", "fastway"]:
            raise HTTPException(
                status_code=400,
                detail=f"Live tracking details not supported or implemented for courier: {order.courier or 'Unknown'}",
            )

        if not order.tracking_number:
            raise HTTPException(
                status_code=400, detail="No tracking number found for this order"
            )

        service = AramexService()
        try:
            details = await service.get_tracking_details(order.tracking_number)
            return {
                "success": True,
                "courier": order.courier,
                "tracking_number": order.tracking_number,
                "data": details,
            }
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Failed to fetch tracking details: {str(e)}"
            )

    async def retry_payment(self, order_id, user, payload, request):
        user_id = user.get("user_id")
        session_token = request.cookies.get("order_token")

        if not user_id and not session_token:
            raise HTTPException(status_code=401, detail="Unauthorized")

        if user_id:
            condition = (Order.id == order_id) & (Order.user_id == user_id)
        else:
            condition = (Order.id == order_id) & (Order.session_token == session_token)

        result = await self.db.execute(
            select(Order).options(selectinload(Order.order_details)).where(condition)
        )
        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(404, "Order not found")

        if order.payment_status != PaymentStatus.FAILED:
            raise HTTPException(
                400,
                f"Retry payment only allowed for FAILED status. Current status: {order.payment_status.value}",
            )

        # Update payment provider from the request
        provider = payload.payment_method.provider

        # Update order details snapshot if it exists
        if order.order_details:
            snapshot = order.order_details.customer_snapshot or {}
            snapshot["payment_method"] = payload.payment_method.model_dump()
            order.order_details.customer_snapshot = snapshot

        payment_payload = {
            "order_id": order.id,
            "amount": int(order.total_amount),
            "provider": provider,
            "currency": order.currency,
            "customer": {
                "user_id": order.user_id,
                "guest_id": order.session_token,
            },
        }
        try:
            logger.info(
                f"Retrying payment for order {order.id} with provider {provider}"
            )
            payment_response = await call_payment_service(payment_payload)
            await log_activity(
                self.db, order.id, "Payment Retry Initiated", user_id=user_id
            )
            await self.db.commit()
            return {
                "order_id": order.id,
                "shipping_cost": order.shipping_cost,
                **payment_response,
            }
        except Exception as e:
            logger.error(f"Payment retry failed: {str(e)}")
            raise HTTPException(
                status_code=400, detail=f"Payment retry initiation failed: {str(e)}"
            )

    async def add_review(self, user, payload):
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated",
            )

        user_id = user.get("user_id")

        stmt = (
            select(Order)
            .options(selectinload(Order.order_details))
            .join(OrderDetails)
            .where(
                Order.user_id == user_id,
                Order.status.in_(
                    [
                        OrderStatus.COMPLETED,
                        OrderStatus.REPLACEMENT,
                        OrderStatus.REFUNDED,
                        OrderStatus.RETURNED,
                    ]
                ),
                Order.actual_delivery_date.isnot(None),
            )
            .order_by(Order.actual_delivery_date.desc())
        )

        result = await self.db.execute(stmt)
        orders = result.scalars().all()

        if not orders:
            raise HTTPException(403, "No delivered orders found")

        matched_order = None
        customer_name = (
            orders[0].order_details.customer_name if orders[0].order_details else None
        )
        user_id = orders[0].user_id

        for order in orders:
            snapshot = order.order_details.customer_snapshot or {}
            products = snapshot.get("products", [])
            for item in products:
                if item.get("product_id") == payload.product_id:
                    matched_order = order
                    break

            if matched_order:
                break

        if not matched_order:
            raise HTTPException(403, "Product not found in delivered orders")

        await call_product_service_add_review(
            payload.product_id,
            user_id,
            customer_name,
            matched_order.id,
            payload.rating,
            payload.comment,
            payload.title,
            payload.images,
        )

        return {"message": "Review submitted successfully"}
