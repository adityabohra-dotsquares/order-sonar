# app/routers/orders.py
from fastapi import (
    APIRouter,
    Depends,
    Query,
    HTTPException,
    Path,
    Request,
    Body,
    File,
    UploadFile,
    Form,
)
from deps import get_db
from schemas.orders import (
    OrderOut,
    OrderStatusUpdate,
    OrderReturnSchema,
    OrderAddressUpdate,
)
from service.orders import update_order_status_logic
from schemas.common import PaginatedResponse
from models.orders import (
    Order,
    OrderStatus,
    OrderReturn,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Annotated
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import Response
from admin_auth import require_superadmin
from schemas.orders import ProcessReturnRequest
from models.orders import ReturnStatus
from typing import List
from service.order_admin import (
    get_available_actions,
    OrderAdminService,
    OrderTimelineService,
)
from service.return_service import ReturnAdminService
from schemas.orders import OrderTagsUpdate

router = APIRouter()


def get_order_admin_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return OrderAdminService(db)


def get_return_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ReturnAdminService(db)


def get_timeline_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return OrderTimelineService(db)


@router.get("/list-orders", response_model=PaginatedResponse[OrderOut])
async def list_orders(
    request: Request,
    response: Response,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 25,
    from_date: Annotated[Optional[str], Query()] = None,
    to_date: Annotated[Optional[str], Query()] = None,
    status: Annotated[Optional[str], Query()] = None,
    warehouse_id: Annotated[Optional[str], Query()] = None,
    courier: Annotated[Optional[str], Query()] = None,
    supplier_id: Annotated[Optional[str], Query()] = None,
    brand: Annotated[Optional[str], Query()] = None,
    min_total: Annotated[Optional[float], Query()] = None,
    max_total: Annotated[Optional[float], Query()] = None,
    q: Annotated[Optional[str], Query()] = None,
    search_field: Annotated[Optional[str], Query()] = "all",
    vendor_id: Annotated[Optional[str], Query()] = None,
    sort_by: Annotated[Optional[str], Query()] = "created_at",
    sort_dir: Annotated[Optional[str], Query()] = "desc",
    download: Annotated[Optional[bool], Query()] = False,
):
    params = {
        "from_date": from_date,
        "to_date": to_date,
        "status": status,
        "warehouse_id": warehouse_id,
        "courier": courier,
        "supplier_id": supplier_id,
        "brand": brand,
        "min_total": min_total,
        "max_total": max_total,
        "q": q,
        "search_field": search_field,
        "vendor_id": vendor_id,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "per_page": per_page,
        "download": download,
    }
    orders, total = await service.list_orders(request, response, params)

    if download:
        return orders  # Actually FileResponse if download=True

    return PaginatedResponse(
        page=page,
        limit=per_page,
        total=total,
        pages=(total + per_page - 1) // per_page,
        data=[OrderOut.model_validate(o, from_attributes=True) for o in orders],
    )


@router.get("/export-orders")
async def export_orders(
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    format: Annotated[str, Query(enum=["excel", "csv"])] = "excel",
    from_date: Annotated[Optional[str], Query()] = None,
    to_date: Annotated[Optional[str], Query()] = None,
    status: Annotated[Optional[str], Query()] = None,
    warehouse_id: Annotated[Optional[str], Query()] = None,
):
    params = {
        "from_date": from_date,
        "to_date": to_date,
        "status": status,
        "warehouse_id": warehouse_id,
    }
    return await service.export_orders(params, format)


@router.get(
    "/get-order/{order_id}",
    response_model=OrderOut,
    responses={404: {"description": "Order not found"}},
)
async def get_order(
    order_id: str,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    return await service.get_order_details(order_id)


@router.patch(
    "/update-orders/{order_id}",
    responses={
        400: {"description": "Invalid status transition or business logic error"},
        404: {"description": "Order not found"},
    },
)
async def update_order_status(
    order_id: Annotated[str, Path(title="The ID of the order to update")],
    status_update: Annotated[OrderStatusUpdate, Body(...)],
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Update the status of an order"""
    return await service.update_order_status(order_id, status_update, user)


@router.patch(
    "/cancel-order-item/{item_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Item already cancelled"},
        404: {"description": "Order item or parent order not found"},
    },
)
async def cancel_order_item(
    item_id: int,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Cancel a single order item (Admin version)"""
    return await service.cancel_order_item(item_id, user)


@router.patch(
    "/ship-order-item/{item_id}",
    response_model=OrderOut,
    responses={
        400: {
            "description": "Item cannot be shipped (e.g., already shipped, cancelled, or invalid order status)"
        },
        404: {"description": "Order item or parent order not found"},
    },
)
async def ship_order_item(
    item_id: int,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    tracking_number: Annotated[Optional[str], Body(embed=True)] = None,
    courier: Annotated[Optional[str], Body(embed=True)] = None,
    quantity: Annotated[Optional[int], Body(embed=True)] = None,
):
    """Mark a single order item as SHIPPED (Admin)"""
    return await service.ship_order_item(item_id, user, tracking_number, courier, quantity)


@router.post(
    "/cancel-order/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Order cannot be cancelled in current status"},
        404: {"description": "Order not found"},
    },
)
async def cancel_order(
    order_id: str,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    reason: Annotated[str, Body(embed=True)],
):
    """Cancel an entire order (Admin)"""
    return await service.cancel_order(order_id, user, reason)


@router.patch(
    "/update-address/{order_id}",
    response_model=OrderOut,
    responses={404: {"description": "Order not found"}},
)
async def update_order_address_endpoint(
    order_id: str,
    address_update: OrderAddressUpdate,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Update shipping and/or billing addresses of an order (Admin)"""
    user_id = user.get("user_id")
    return await service.update_order_address(order_id, address_update, user_id)


def get_return_available_actions(return_req):
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


@router.get(
    "/return-request/{return_id}",
    response_model=OrderReturnSchema,
    responses={404: {"description": "Return Request not found"}},
)
async def get_return_request(
    return_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Get a specific return request details (Admin)"""
    result = await db.execute(
        select(OrderReturn)
        .options(
            selectinload(OrderReturn.items),
            selectinload(OrderReturn.order).selectinload(Order.order_details),
        )
        .where(OrderReturn.id == return_id)
    )
    return_req = result.scalar_one_or_none()

    if not return_req:
        raise HTTPException(404, "Return Request not found")

    return_req.available_actions = get_return_available_actions(return_req)
    if return_req.order:
        return_req.order.available_actions = get_available_actions(return_req.order)

    return return_req


@router.post(
    "/return-order/{order_id}",
    response_model=OrderOut,
    responses={
        400: {
            "description": "Return request failed (e.g., order not delivered or processing error)"
        },
        404: {"description": "Order not found"},
    },
)
async def return_order(
    order_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[dict, Depends(require_superadmin)],
    reason: Annotated[str, Body(embed=True)],
):
    """Request return for an order (Admin)"""
    user_id = user.get("user_id")
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.order_details))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(404, "Order not found")

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(400, "Only delivered orders can be returned")

    try:
        await update_order_status_logic(
            db,
            order,
            OrderStatus.RETURNED,
            user_id=user_id,
            notes=f"Return Reason: {reason}",
        )
        await db.commit()
        await db.refresh(order)
        order.available_actions = get_available_actions(order)
        return order
    except Exception as e:
        await db.rollback()
        raise HTTPException(400, f"Return request failed: {str(e)}")


@router.get("/return-request/{return_id}", response_model=OrderReturnSchema)
async def get_return_request(
    return_id: str,
    service: Annotated[ReturnAdminService, Depends(get_return_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Get a specific return request details (Admin)"""
    return await service.get_admin_return_request(return_id)


@router.post(
    "/return-order/{order_id}",
    response_model=OrderOut,
    responses={
        400: {
            "description": "Return request failed (e.g., order not delivered or processing error)"
        },
        404: {"description": "Order not found"},
    },
)
async def return_order(
    order_id: str,
    service: Annotated[ReturnAdminService, Depends(get_return_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    reason: Annotated[str, Body(embed=True)],
):
    """Request return for an order (Admin)"""
    user_id = user.get("user_id")
    return await service.admin_return_order(order_id, user_id, reason)


@router.post(
    "/return-order-item/{item_id}",
    response_model=OrderOut,
    responses={
        400: {
            "description": "Invalid return request (e.g., order not delivered or item already returned)"
        },
        404: {"description": "Order item or parent order not found"},
    },
)
async def return_order_item(
    item_id: int,
    service: Annotated[ReturnAdminService, Depends(get_return_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    reason: Annotated[str, Body(embed=True)],
):
    """
    Return a single order item (Admin).
    Updates Order status to PARTIALLY_RETURNED or RETURNED.
    """
    user_id = user.get("user_id")
    return await service.admin_return_order_item(item_id, user_id, reason)


@router.post(
    "/process-refund/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Invalid refund amount or status"},
        404: {"description": "Order not found"},
    },
)
async def process_refund(
    order_id: str,
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    amount: Annotated[float, Body(embed=True)],
    reason: Annotated[str, Body(embed=True)],
):
    """Process refund for an order (Admin)"""
    return await service.process_refund(order_id, user, amount, reason)


@router.delete(
    "/delete-all-order",
    status_code=204,
    responses={500: {"description": "Failed to delete orders"}},
)
async def delete_all_orders(
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """
    Delete ALL orders.
    WARNING: This action is irreversible.
    """
    return await service.delete_all_orders()


@router.get(
    "/list-return-requests", response_model=PaginatedResponse[OrderReturnSchema]
)
async def list_return_requests(
    user: Annotated[dict, Depends(require_superadmin)],
    service: Annotated[ReturnAdminService, Depends(get_return_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1)] = 25,
    status: Annotated[Optional[str], Query()] = None,
    order_id: Annotated[Optional[str], Query()] = None,
):
    """List return requests (Admin)"""
    returns, total = await service.list_returns(page, per_page, status, order_id)

    return PaginatedResponse(
        page=page,
        limit=per_page,
        total=total,
        pages=(total + per_page - 1) // per_page,
        data=[
            OrderReturnSchema.model_validate(r, from_attributes=True) for r in returns
        ],
    )


@router.post(
    "/process-return/{return_id}",
    response_model=OrderReturnSchema,
    responses={
        400: {"description": "Invalid return process action or status"},
        404: {"description": "Return request or associated order not found"},
    },
)
async def process_return(
    return_id: str,
    payload: Annotated[ProcessReturnRequest, Body(...)],
    service: Annotated[ReturnAdminService, Depends(get_return_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """Process a return request (Approve/Reject)"""
    return await service.process_return(return_id, payload, user.get("user_id"))


@router.post(
    "/orders/{order_id}/timeline",
    responses={
        404: {"description": "Order not found"},
        502: {"description": "GCS upload failure"},
    },
)
async def add_timeline_entry(
    order_id: str,
    text: Annotated[str, Form(...)],
    service: Annotated[OrderTimelineService, Depends(get_timeline_service)],
    user: Annotated[dict, Depends(require_superadmin)],
    files: Annotated[Optional[List[UploadFile]], File()] = None,
):
    """
    Add a custom note/attachment to the order timeline.
    """
    new_entry = await service.add_order_timeline(order_id, text, [], user, files)

    return {
        "status": "success",
        "data": {
            "id": new_entry.id,
            "text": new_entry.text,
            "attachments": new_entry.attachments,
            "created_at": (
                new_entry.created_at.isoformat() if new_entry.created_at else None
            ),
        },
    }


@router.patch(
    "/update-tags/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Failed to update tags"},
        404: {"description": "Order not found"},
    },
)
async def update_order_tags(
    order_id: Annotated[str, Path(title="The ID of the order to update tags for")],
    payload: Annotated[OrderTagsUpdate, Body(...)],
    service: Annotated[OrderAdminService, Depends(get_order_admin_service)],
    user: Annotated[dict, Depends(require_superadmin)],
):
    """
    Update the tags of an order
    """
    return await service.update_order_tags(order_id, payload.tags)
