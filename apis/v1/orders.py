from fastapi import (
    APIRouter,
    Depends,
    Query,
    HTTPException,
    Path,
    Request,
    Body,
)
from deps import get_db
from schemas.orders import (
    OrderCreate,
    OrderOut,
    OrderStatusUpdate,
    PaymentStatusUpdate,
)
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from models.orders import (
    OrderStatus,
)
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Annotated
from service.shipstation_service import (
    ShipStationService,
)
from apis.v1.shipstation import get_shipstation_service
from fastapi import Response
from utils.user_auth import get_current_user
from dotenv import load_dotenv
import os
from schemas.orders import AddReviewRequest
from service.order_service import OrderService
from schemas.orders import RetryPaymentRequest
from schemas.orders import ReturnRequest, OrderReturnSchema

load_dotenv()

PRODUCT_BASE_URL = os.getenv(
    "PRODUCT_URL",
    "https://shopper-beats-products-877627218975.australia-southeast2.run.app",
)
templates = Jinja2Templates(directory="templates")
router = APIRouter()


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


class PaginationParams:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        per_page: Annotated[int, Query(ge=1)] = 25,
    ):
        self.page = page
        self.per_page = per_page


class SortingParams:
    def __init__(
        self,
        sort_by: Annotated[Optional[str], Query()] = "created_at",
        sort_dir: Annotated[Optional[str], Query()] = "desc",
    ):
        self.sort_by = sort_by
        self.sort_dir = sort_dir


class OrderFilterParams:
    def __init__(
        self,
        pagination: Annotated[PaginationParams, Depends()],
        sorting: Annotated[SortingParams, Depends()],
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
        download: Annotated[Optional[bool], Query()] = False,
    ):
        self.pagination = pagination
        self.sorting = sorting
        self.from_date = from_date
        self.to_date = to_date
        self.status = status
        self.warehouse_id = warehouse_id
        self.courier = courier
        self.supplier_id = supplier_id
        self.brand = brand
        self.min_total = min_total
        self.max_total = max_total
        self.q = q
        self.download = download


@router.get(
    "/list-orders",
    response_model=dict,
    responses={
        401: {"description": "Unauthorized: User id or session token is required"}
    },
)
async def list_orders(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[dict, Depends(get_current_user)],
    request: Request,
    response: Response,
    filters: Annotated[OrderFilterParams, Depends()],
):
    service = get_order_service(db)
    orders, total = await service.list_orders(request, user, filters)
    return {
        "page": filters.pagination.page,
        "per_page": filters.pagination.per_page,
        "total_items": total,
        "total_pages": (total + filters.pagination.per_page - 1)
        // filters.pagination.per_page,
        "data": [OrderOut.model_validate(o, from_attributes=True) for o in orders],
    }


def get_order_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return OrderService(db)


@router.get(
    "/get-order/{order_id}",
    response_model=OrderOut,
    responses={
        401: {"description": "Unauthorized: User id or session token is required"},
        404: {"description": "Order not found"},
    },
)
async def get_order(
    order_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    user_id = user.get("user_id", None)
    order = await service.get_order(
        order_id,
        filters=[],
        includes=["order_details", "items", "courier_partner"],
        user_id=user_id,
    )
    return order


@router.get(
    "/get-order/{order_id}/tracking-details",
    responses={
        400: {
            "description": "Tracking details not supported or missing tracking number"
        },
        401: {"description": "Unauthorized: User id or session token is required"},
        404: {"description": "Order not found"},
    },
)
async def get_order_tracking_details(
    order_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    """Fetch live tracking details for Aramex/Fastway orders"""
    return await service.get_order_tracking_details(order_id, user)


@router.post(
    "/create-orders",
    status_code=201,
    responses={
        400: {
            "description": "Failed to create order (e.g., sync or payment initiation failure)"
        }
    },
)
async def create_order(
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    # shipstation_service: Annotated[ShipStationService, Depends(get_shipstation_service)],
    request: Request,
    response: Response,
    order: OrderCreate,
):
    user_id = user.get("user_id", None)
    return await service.create_order(order, user_id, request, response)


@router.patch(
    "/update-orders/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Invalid status update or ShipStation sync failure"},
        404: {"description": "Order not found"},
    },
)
async def update_order_status(
    user: Annotated[dict, Depends(get_current_user)],
    shipstation_service: Annotated[
        ShipStationService, Depends(get_shipstation_service)
    ],
    order_id: Annotated[str, Path(title="The ID of the order to update")],
    status_update: Annotated[OrderStatusUpdate, Body(...)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    """Update the status of an order"""
    logger.info("###UPDATE ORDER STATUS")
    updated_order = await service.update_order_status(
        order_id, user, status_update, shipstation_service
    )
    return updated_order


@router.post(
    "/update-payment-status/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Failed to update payment status"},
        404: {"description": "Order not found"},
    },
)
async def update_payment_status(
    order_id: Annotated[str, Path(title="The ID of the order")],
    payload: Annotated[PaymentStatusUpdate, Body(...)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    """
    Update payment status (e.g. via webhook or manual admin action).
    Trigger order status transition if payment becomes PAID.
    """
    logger.info("###UPDATE PAYMENT STATUS", order_id, payload)
    return await service.update_payment_status(order_id, payload)


@router.post(
    "/retry-payment/{order_id}",
    responses={
        400: {"description": "Payment retry not allowed or failed"},
        401: {"description": "Unauthorized"},
        404: {"description": "Order find not found"},
    },
)
async def retry_payment(
    user: Annotated[dict, Depends(get_current_user)],
    order_id: Annotated[str, Path(title="The ID of the order to retry payment for")],
    payload: Annotated[RetryPaymentRequest, Body(...)],
    request: Request,
    service: Annotated[OrderService, Depends(get_order_service)],
):
    return await service.retry_payment(order_id, user, payload, request)


@router.get(
    "/get-invoice/{order_id}",
    response_class=HTMLResponse,
    responses={404: {"description": "Order not found"}},
)
async def get_invoice(
    order_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Generate HTML Invoice for an order"""
    user_id = user.get("user_id")
    order_service = OrderService(db)
    order = await order_service.get_order(
        order_id,
        includes=["order_details", "items", "courier_partner"],
        user_id=user_id,
    )
    return templates.TemplateResponse(
        "invoice.html", {"request": request, "order": order}
    )


@router.post(
    "/add-review",
    responses={
        401: {"description": "User not authenticated"},
        403: {"description": "No delivered orders found for this product"},
    },
)
async def add_review(
    user: Annotated[dict, Depends(get_current_user)],
    payload: Annotated[AddReviewRequest, Body(...)],
    service: Annotated[OrderService, Depends(get_order_service)],
):
    return await service.add_review(user, payload)


@router.patch(
    "/cancel-order-item/{item_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Item cannot be cancelled (already cancelled or shipped)"},
        404: {"description": "Order item or parent order not found"},
    },
)
async def cancel_order_item(
    item_id: str,
    service: Annotated[OrderService, Depends(get_order_service)],
    user: Annotated[dict, Depends(get_current_user)],
):
    return await service.cancel_order_item(item_id, user)


@router.post(
    "/cancel-order/{order_id}",
    response_model=OrderOut,
    responses={
        400: {"description": "Order cannot be cancelled in current status"},
        401: {"description": "Unauthorized"},
        404: {"description": "Order not found"},
    },
)
async def cancel_order(
    order_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    reason: Annotated[str, Body(embed=True)],
):
    """Cancel an entire order (Customer)"""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await service.cancel_order(order_id, user_id, reason)


@router.post(
    "/return-order/{order_id}",
    response_model=OrderReturnSchema,
    responses={
        400: {"description": "Return already requested or order not delivered"},
        404: {"description": "Order not found"},
    },
)
async def return_order(
    order_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    payload: Annotated[ReturnRequest, Body(...)],
):
    """Request return for an order (Customer)"""
    return await service.return_order(order_id, payload, user)


@router.post(
    "/return-order-item/{item_id}",
    response_model=OrderReturnSchema,
    responses={
        400: {
            "description": "Return already exists for this item or order not delivered"
        },
        401: {"description": "Unauthorized"},
        404: {"description": "Order item or parent order not found"},
    },
)
async def return_order_item(
    item_id: int,
    user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
    payload: Annotated[ReturnRequest, Body(...)],
):
    """
    Return a single order item (Customer).
    Creates a return request for the specific item.
    """
    return await service.return_order_item(item_id, payload, user)
