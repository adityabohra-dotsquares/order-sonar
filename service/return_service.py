from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from models.orders import OrderReturn, Order, ReturnStatus, PaymentStatus, OrderStatus
from models.return_reasons import ReturnReason
from schemas.return_reasons import ReturnReasonCreate, ReturnReasonUpdate
from service.order_base_service import OrderBaseService
from utils.constants import messages
from service.orders import (
    log_activity,
    call_payment_refund,
    update_order_status_logic,
    create_replacement_order,
)
import uuid
from typing import Optional, List


class ReturnRepository:
    def __init__(self, db):
        self.db = db

    async def get_return_by_id(self, return_id):
        result = await self.db.execute(
            select(OrderReturn)
            .options(
                selectinload(OrderReturn.items),
                selectinload(OrderReturn.order).selectinload(Order.order_details),
            )
            .where(OrderReturn.id == return_id)
        )
        return result.scalar_one_or_none()


class ReturnBaseService:
    def __init__(self, db):
        self.db = db

    def repo(self):
        return ReturnRepository(self.db)

    async def get_return_or_404(self, return_id):
        response = await self.repo().get_return_by_id(return_id)
        if not response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Return not found"
            )
        return response


class ReturnAdminService(ReturnBaseService):
    def __init__(self, db):
        super().__init__(db)

    def get_return_available_actions(self, return_req):
        actions = []
        if return_req.status == ReturnStatus.REQUESTED:
            actions.extend(["approve", "reject"])
        if return_req.status == ReturnStatus.APPROVED:
            actions.append("returned")
            if return_req.return_type == "replacement":
                actions.append("replace")
            else:
                actions.append("refund")
        return actions

    async def list_returns(
        self,
        page: int = 1,
        per_page: int = 25,
        status: Optional[str] = None,
        order_id: Optional[str] = None,
    ):
        """List return requests (Admin) with filters and pagination"""
        offset = (page - 1) * per_page
        query = select(OrderReturn).options(
            selectinload(OrderReturn.items),
            selectinload(OrderReturn.order).selectinload(Order.order_details),
        )

        if status:
            query = query.where(OrderReturn.status == ReturnStatus(status))
        if order_id:
            query = query.where(OrderReturn.order_id == order_id)

        query = query.order_by(OrderReturn.created_at.desc())

        # Total count
        from sqlalchemy import func

        count_query = select(func.count(OrderReturn.id))
        if status:
            count_query = count_query.where(OrderReturn.status == ReturnStatus(status))
        if order_id:
            count_query = count_query.where(OrderReturn.order_id == order_id)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        result = await self.db.execute(query.offset(offset).limit(per_page))
        returns = result.scalars().all()

        from service.order_admin import get_available_actions

        # Populate available actions
        for r in returns:
            r.available_actions = self.get_return_available_actions(r)
            if r.order:
                from service.order_admin import get_available_actions
                r.order.available_actions = get_available_actions(r.order)

        return returns, total

    # --- Return Reasons CRUD ---

    async def list_return_reasons(self, is_active: Optional[bool] = None) -> List[ReturnReason]:
        """List all return reasons with optional activity filter."""
        stmt = select(ReturnReason)
        if is_active is not None:
            stmt = stmt.where(ReturnReason.is_active == is_active)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_return_reason(self, reason_id: str) -> ReturnReason:
        """Fetch a specific return reason by ID."""
        result = await self.db.execute(select(ReturnReason).where(ReturnReason.id == reason_id))
        reason = result.scalar_one_or_none()
        if not reason:
            raise HTTPException(404, messages.get("return_reason_not_found"))
        return reason

    async def create_return_reason(self, payload: ReturnReasonCreate) -> ReturnReason:
        """Create a new return reason."""
        reason = ReturnReason(**payload.model_dump())
        self.db.add(reason)
        await self.db.commit()
        await self.db.refresh(reason)
        return reason

    async def update_return_reason(self, reason_id: str, payload: ReturnReasonUpdate) -> ReturnReason:
        """Update an existing return reason."""
        reason = await self.get_return_reason(reason_id)
        update_data = payload.model_dump(exclude_unset=True)
        for k, v in update_data.items():
            setattr(reason, k, v)
        await self.db.commit()
        await self.db.refresh(reason)
        return reason

    async def delete_return_reason(self, reason_id: str):
        """Delete a return reason."""
        reason = await self.get_return_reason(reason_id)
        await self.db.delete(reason)
        await self.db.commit()

    async def get_admin_return_request(self, return_id: str):
        """Get a specific return request details (Admin)"""
        return_req = await self.get_return_or_404(return_id)
        
        from service.order_admin import get_available_actions
        
        return_req.available_actions = self.get_return_available_actions(return_req)
        if return_req.order:
            return_req.order.available_actions = get_available_actions(return_req.order)
        return return_req

    async def admin_return_order(self, order_id: str, user_id: str, reason: str):
        """Request return for an entire order (Admin)"""
        order = await OrderBaseService(self.db).get_order_or_404(
            order_id, includes=["items", "order_details"]
        )

        if order.status != OrderStatus.DELIVERED:
            raise HTTPException(400, "Only delivered orders can be returned")

        try:
            from service.order_admin import get_available_actions
            
            await update_order_status_logic(
                self.db,
                order,
                OrderStatus.RETURNED,
                user_id=user_id,
                notes=f"Return Reason: {reason}",
            )
            await self.db.commit()
            await self.db.refresh(order)
            order.available_actions = get_available_actions(order)
            return order
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Return request failed: {str(e)}")

    async def admin_return_order_item(self, item_id: int, user_id: str, reason: str):
        """Return a single order item (Admin)"""
        from models.orders import OrderItem
        from service.order_admin import get_available_actions

        # 1. Fetch Item & Order
        item_result = await self.db.execute(select(OrderItem).where(OrderItem.id == item_id))
        item = item_result.scalar_one_or_none()
        if not item:
            raise HTTPException(404, "Order Item not found")

        order = await OrderBaseService(self.db).get_order_or_404(
            item.order_id, includes=["items", "order_details"]
        )

        # 2. Validation
        if order.status not in [OrderStatus.DELIVERED, OrderStatus.PARTIALLY_RETURNED]:
            raise HTTPException(400, "Order must be Delivered to initiate return")

        if item.status == OrderStatus.RETURNED:
            raise HTTPException(400, "Item already returned")

        try:
            # 3. Update Item Status
            item.status = OrderStatus.RETURNED

            # 4. Determine Parent Order Status
            all_returned = all(
                i.status == OrderStatus.RETURNED or i.id == item.id for i in order.items
            )
            new_order_status = (
                OrderStatus.RETURNED if all_returned else OrderStatus.PARTIALLY_RETURNED
            )

            # 5. Update Order
            if order.status != new_order_status:
                await update_order_status_logic(
                    self.db,
                    order,
                    new_order_status,
                    user_id=user_id,
                    notes=f"Item {item.name} Returned. Reason: {reason}",
                )
            else:
                await log_activity(
                    self.db,
                    order.id,
                    "Item Returned",
                    user_id=user_id,
                    description=f"Item {item.name} status -> Returned",
                )

            await self.db.commit()
            await self.db.refresh(order)
            order.available_actions = get_available_actions(order)
            return order

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(400, f"Item Return failed: {str(e)}")

    async def process_return(self, return_id, payload, user_id):
        return_req = await self.get_return_or_404(return_id)
        order = await OrderBaseService(self.db).get_order_or_404(return_req.order_id)
        try:
            if payload.action == "approve":
                if return_req.status != ReturnStatus.REQUESTED:
                    raise HTTPException(
                        400,
                        f"Cannot process return in status {return_req.status.value}",
                    )
                # Step 1: Confirm/Approve the return (customer can send items back)
                return_req.status = ReturnStatus.APPROVED
                if payload.admin_notes:
                    return_req.admin_notes = payload.admin_notes

                # Log approval
                await log_activity(
                    self.db,
                    order.id,
                    "Return Approved",
                    user_id=user_id,
                    description=f"Return ID {return_id} approved. Customer can proceed with return.",
                )

            elif payload.action == "refund":
                # Step 2: Issue refund (after receiving returned items)
                # Can refund REQUESTED (auto-approve) or APPROVED returns
                if return_req.status not in [
                    ReturnStatus.REQUESTED,
                    ReturnStatus.APPROVED,
                ]:
                    raise HTTPException(
                        400, f"Cannot refund return in status {return_req.status.value}"
                    )

                # Auto-approve if needed
                if return_req.status == ReturnStatus.REQUESTED:
                    return_req.status = ReturnStatus.APPROVED
                    await log_activity(
                        self.db,
                        order.id,
                        "Return Auto-Approved (for refund)",
                        user_id=user_id,
                        description=f"Return ID {return_id} auto-approved to process refund.",
                    )

                if not payload.refund_amount:
                    raise HTTPException(
                        400, "refund_amount is required for refund action"
                    )

                # Generate idempotency key
                idempotency_key = f"ref_ret_{return_id}_{uuid.uuid4().hex[:8]}"

                # Call payment service for refund
                payment_payload = {
                    "order_id": order.id,
                    "amount": payload.refund_amount,
                    "currency": order.currency or "INR",
                    "reason": payload.admin_notes or "Return Refund",
                }
                if len(return_req.items) == 1:
                    payment_payload["order_item_id"] = str(
                        return_req.items[0].order_item_id
                    )

                await call_payment_refund(
                    payment_payload, idempotency_key=idempotency_key
                )

                return_req.status = ReturnStatus.REFUNDED
                return_req.refund_amount = payload.refund_amount
                if payload.admin_notes:
                    return_req.admin_notes = payload.admin_notes

                # Process refund amount on order
                total_refunded = float(order.refund_amount or 0) + float(
                    payload.refund_amount
                )
                order.refund_amount = total_refunded

                # Update Payment Status
                if total_refunded >= float(order.total_amount or 0):
                    order.payment_status = PaymentStatus.REFUNDED
                    new_order_status = OrderStatus.REFUNDED
                else:
                    order.payment_status = PaymentStatus.PARTIALLY_REFUNDED
                    new_order_status = OrderStatus.PARTIALLY_REFUNDED

                # Update Order Status (Transitioning from RETURNED to REFUNDED/PARTIALLY_REFUNDED)
                await update_order_status_logic(
                    self.db,
                    order,
                    new_order_status,
                    user_id=user_id,
                    notes=f"Return Refunded. ID: {return_id}. Amount: {payload.refund_amount}",
                )

                # Update Item Statuses
                return_item_ids = {ri.order_item_id for ri in return_req.items}
                for item in order.items:
                    if item.id in return_item_ids:
                        item.status = OrderStatus.REFUNDED

                # Log refund
                await log_activity(
                    self.db,
                    order.id,
                    "Refund Issued",
                    user_id=user_id,
                    description=f"Refund of {payload.refund_amount} issued for Return ID {return_id}",
                )

            elif payload.action == "reject":
                if return_req.status != ReturnStatus.REQUESTED:
                    raise HTTPException(
                        400,
                        f"Cannot process return in status {return_req.status.value}",
                    )
                return_req.status = ReturnStatus.REJECTED
                if payload.admin_notes:
                    return_req.admin_notes = payload.admin_notes

                # Log rejection on order
                await log_activity(
                    self.db,
                    order.id,
                    "Return Rejected",
                    user_id=user_id,
                    description=f"Return ID {return_id} rejected. Reason: {payload.admin_notes}",
                )

                # Revert order status
                await update_order_status_logic(
                    self.db,
                    order,
                    OrderStatus.DELIVERED,
                    user_id=user_id,
                    notes=f"Return request {return_id} rejected. Reverting to Delivered.",
                )

            elif payload.action == "returned":
                # Mark order as returned (received)
                await update_order_status_logic(
                    self.db,
                    order,
                    OrderStatus.RETURNED,
                    user_id=user_id,
                    notes=f"Item(s) for Return ID {return_id} received at warehouse.",
                )
                if payload.admin_notes:
                    return_req.admin_notes = payload.admin_notes

            elif payload.action == "replace":
                # Step 3: Issue replacement (after receiving returned items)
                # Can replace REQUESTED (auto-approve) or APPROVED returns
                if return_req.status not in [
                    ReturnStatus.REQUESTED,
                    ReturnStatus.APPROVED,
                ]:
                    raise HTTPException(
                        400,
                        f"Cannot replace return in status {return_req.status.value}",
                    )

                # Auto-approve if needed
                if return_req.status == ReturnStatus.REQUESTED:
                    return_req.status = ReturnStatus.APPROVED
                    await log_activity(
                        self.db,
                        order.id,
                        "Return Auto-Approved (for replacement)",
                        user_id=user_id,
                        description=f"Return ID {return_id} auto-approved to process replacement.",
                    )

                # Create replacement order using service logic
                new_replacement_order = await create_replacement_order(
                    self.db, order, return_req
                )

                # Update return request status
                return_req.status = ReturnStatus.REPLACED
                return_req.replacement_order_id = new_replacement_order.id
                if payload.admin_notes:
                    return_req.admin_notes = payload.admin_notes

                # Update original order status
                await update_order_status_logic(
                    self.db,
                    order,
                    OrderStatus.REPLACEMENT,
                    user_id=user_id,
                    notes=f"Replacement issued. New Order: {new_replacement_order.order_number}",
                )

                # Log activity on original order
                await log_activity(
                    self.db,
                    order.id,
                    "Replacement Ordered",
                    user_id=user_id,
                    description=f"Replacement order {new_replacement_order.order_number} created for Return ID {return_id}",
                )

                # Log activity on new order
                await log_activity(
                    self.db,
                    new_replacement_order.id,
                    "Order Created (Replacement)",
                    user_id=user_id,
                    description=f"This order is a replacement for Order {order.order_number}",
                )

            await self.db.commit()

            # Re-fetch with needed relationships to avoid lazy-loading after commit
            stmt = (
                select(OrderReturn)
                .options(
                    selectinload(OrderReturn.items),
                    selectinload(OrderReturn.order).selectinload(Order.order_details),
                )
                .where(OrderReturn.id == return_id)
            )
            result = await self.db.execute(stmt)
            return_req = result.scalar_one()

            return_req.available_actions = self.get_return_available_actions(return_req)
            if return_req.order:
                return_req.order.available_actions = self.get_available_actions(
                    return_req.order
                )

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(500, str(e))
