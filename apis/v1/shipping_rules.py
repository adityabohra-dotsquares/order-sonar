from fastapi import APIRouter, Depends, File, UploadFile, status, Query
from typing import List, Annotated, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.shipping_rules import (
    ShippingRuleCreate,
    ShippingRuleOut,
    ShippingZoneCreate,
    ShippingZoneOut,
    CarrierRateCreate,
    CarrierRateOut,
    CalculateRequest,
    CalculateResponse,
    RateByZoneCreate,
    RateByZoneResponse,
    RateByZoneUpdate,
    CartShippingRequest,
    CartShippingResponse,
    ShippingCalculationResponse,
)
from service.shipping_rule_service import ShippingRuleService
from service.zone_service import ZoneService
from service.zone_rate_import import import_rates_by_zone

router = APIRouter()

def get_shipping_rule_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ShippingRuleService(db)

def get_zone_service(db: Annotated[AsyncSession, Depends(get_db)]):
    # Some endpoints might still need ZoneService logic for RateByZone
    return ZoneService(db)

# Rules CRUD
@router.post("/create-rules/", response_model=ShippingRuleOut)
async def create_rule(
    payload: ShippingRuleCreate,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Create a new Shipping Rule"""
    return await service.create_rule(payload)

@router.get("/list-rules/", response_model=List[ShippingRuleOut])
async def list_rules(
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)]
):
    """List all Shipping Rules"""
    return await service.list_rules()

@router.get(
    "/get-rules/{rule_id}",
    response_model=ShippingRuleOut,
    responses={404: {"description": "Rule not found"}},
)
async def get_rule(
    rule_id: str,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Get a Shipping Rule by ID"""
    return await service.get_rule(rule_id)

@router.put(
    "/update-rules/{rule_id}",
    response_model=ShippingRuleOut,
    responses={404: {"description": "Rule not found"}},
)
async def update_rule(
    rule_id: str,
    payload: ShippingRuleCreate,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Update a Shipping Rule"""
    return await service.update_rule(rule_id, payload)

@router.delete(
    "/delete-rules/{rule_id}",
    responses={404: {"description": "Rule not found"}},
)
async def delete_rule(
    rule_id: str,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Delete a Shipping Rule"""
    return await service.delete_rule(rule_id)

# Zones CRUD (Legacy)
@router.post("/create-zones/", response_model=ShippingZoneOut)
async def create_zone(
    payload: ShippingZoneCreate,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Create a legacy Shipping Zone"""
    return await service.create_zone(payload)

@router.get("/list-zones/", response_model=List[ShippingZoneOut])
async def list_zones(
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)]
):
    """List all legacy Shipping Zones"""
    return await service.list_zones()

# Carrier Rates CRUD
@router.post("/carriers/", response_model=CarrierRateOut)
async def create_carrier_rate(
    payload: CarrierRateCreate,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Create a Carrier Rate"""
    return await service.create_carrier_rate(payload)

@router.get("/carriers/", response_model=List[CarrierRateOut])
async def list_carrier_rates(
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)]
):
    """List all Carrier Rates"""
    return await service.list_carrier_rates()

# Shipping calculate endpoint (Legacy/General)
@router.post(
    "/calculate",
    response_model=CalculateResponse,
    responses={400: {"description": "Pincode not found"}},
)
async def calculate(
    payload: CalculateRequest,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Calculate shipping cost based on general rules (weight/price)"""
    return await service.calculate(payload)

# Rate By Zone Endpoints (conceptually overlapping with rate_by_zones.py)
@router.post(
    "/add-rates-by-zone",
    response_model=RateByZoneResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Rate already exists"}},
)
async def create_rate_by_zone(
    payload: RateByZoneCreate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Add a rate for a product in a zone"""
    # Note: ZoneService uses product_identifier in its schema. 
    # If the schemas for this endpoint differ slightly, we might need a translation.
    # But looking at models, they use same RateByZone.
    # Translating manually if needed for compatibility with specific schema
    from schemas.rate_by_zones import RateByZoneCreate as ZoneSvcPayload
    svc_payload = ZoneSvcPayload(
        product_identifier=payload.product_id,
        zone_code=payload.zone,
        rate=payload.rate,
        is_active=payload.is_active
    )
    return await service.create_rate_by_zone(svc_payload)

@router.get(
    "/list-rates-by-zone",
    response_model=List[RateByZoneResponse],
)
async def list_rates_by_zone(
    service: Annotated[ZoneService, Depends(get_zone_service)],
    zone: Annotated[Optional[str], Query()] = None,
    product_id: Annotated[Optional[str], Query()] = None,
):
    """List all rates by zone"""
    resp = await service.list_rates_by_zone(
        zone_code=zone, product_identifier=product_id, limit=-1
    )
    return resp.get("data", [])

@router.get(
    "/get-rates-by-zone/{rate_id}",
    response_model=RateByZoneResponse,
    responses={404: {"description": "Rate not found"}},
)
async def get_rate_by_zone(
    rate_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Get a rate by ID"""
    result = await service.db.execute(service.repo()._select_rate_by_id(rate_id))
    rate = result.scalar_one_or_none()
    if not rate:
        raise HTTPException(status_code=404, detail="Rate not found")
    return rate

@router.delete(
    "/delete-rates-by-zone/{rate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "Rate not found"}},
)
async def delete_rate_by_zone(
    rate_id: str,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Delete a rate by ID"""
    await service.delete_rate_by_zone(rate_id)
    return

@router.put(
    "/update-rates-by-zone/{rate_id}",
    response_model=RateByZoneResponse,
    responses={404: {"description": "Rate not found"}},
)
async def update_rate_by_zone(
    rate_id: str,
    payload: RateByZoneUpdate,
    service: Annotated[ZoneService, Depends(get_zone_service)],
):
    """Update a rate by ID"""
    from schemas.rate_by_zones import RateByZoneUpdate as ZoneSvcUpdate
    svc_payload = ZoneSvcUpdate(
        rate=payload.rate,
        is_active=payload.is_active
    )
    return await service.update_rate_by_zone(rate_id, svc_payload)

@router.post(
    "/import-rates-by-zone",
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Invalid format"}},
)
async def import_rate_by_zone_file(
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()] = ...,
):
    """Import rates from a file"""
    file_bytes = await file.read()
    created = await import_rates_by_zone(
        file_bytes=file_bytes,
        filename=file.filename,
        db=db,
    )
    return {"message": created}

@router.get(
    "/calculate-shipping",
    response_model=ShippingCalculationResponse,
)
async def calculate_shipping(
    postcode: Annotated[str, Query()],
    product_identifier: Annotated[str, Query()],
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Calculate shipping for product + postcode"""
    return await service.calculate_shipping(postcode, product_identifier)

@router.post("/calculate-cart-shipping", response_model=CartShippingResponse)
async def calculate_cart_shipping(
    payload: CartShippingRequest,
    service: Annotated[ShippingRuleService, Depends(get_shipping_rule_service)],
):
    """Calculate shipping for full cart"""
    return await service.calculate_cart_shipping(payload)
