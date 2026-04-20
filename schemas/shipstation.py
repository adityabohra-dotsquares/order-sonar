# app/schemas/shipstation.py
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from typing import Literal


class Address(BaseModel):
    name: str
    company: Optional[str] = None
    street1: str
    street2: Optional[str] = None
    street3: Optional[str] = None
    city: str
    state: str
    postalCode: str
    country: str
    phone: Optional[str] = None


class Weight(BaseModel):
    value: float
    units: Literal["pounds", "ounces", "grams"]


class Dimension(BaseModel):
    length: float
    width: float
    height: float
    units: Literal["inches", "centimeters"]


class RateRequest(BaseModel):
    carrierCode: Optional[str] = None  # Specific carrier or all carriers
    serviceCode: Optional[str] = None
    packageCode: Optional[str] = None
    fromPostalCode: str  # Origin zipcode
    toState: str
    toCountry: str
    toPostalCode: str
    toCity: str
    weight: Weight
    dimensions: Optional[Dimension] = None
    confirmation: Optional[str] = None
    residential: bool = False


class ShippingRate(BaseModel):
    serviceName: str
    serviceCode: str
    shipmentCost: float
    otherCost: float
    carrierCode: Optional[str] = None
    carrierName: Optional[str] = None
    deliveryDays: Optional[int] = None
    estimatedDeliveryDate: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "ignore"


class RateResponse(BaseModel):
    rates: List[ShippingRate]


# Existing models remain the same...
class OrderItem(BaseModel):
    lineItemKey: Optional[str] = None
    sku: str
    name: str
    imageUrl: Optional[str] = None
    weight: Optional[Dict[str, Any]] = None
    quantity: int
    unitPrice: float
    warehouseLocation: Optional[str] = None


class ShipStationOrder(BaseModel):
    orderNumber: str
    orderKey: Optional[str] = None
    orderDate: str
    paymentDate: str
    orderStatus: str = "awaiting_shipment"
    customerUsername: Optional[str] = None
    customerEmail: EmailStr
    billTo: Address
    shipTo: Address
    items: List[OrderItem]
    amountPaid: float
    taxAmount: float
    shippingAmount: float
    carrierCode: Optional[str] = None
    serviceCode: Optional[str] = None
    packageCode: Optional[str] = None
    confirmation: Optional[str] = None
    insuranceOptions: Optional[Dict[str, Any]] = None


class ShipmentRequest(BaseModel):
    carrierCode: str
    serviceCode: str
    packageCode: str = "package"
    confirmation: str = "none"
    insuranceOptions: Optional[Dict[str, Any]] = None
    advancedOptions: Optional[Dict[str, Any]] = None


class CarrierResponse(BaseModel):
    carriers: List[Dict[str, Any]]


class OrderRequest(BaseModel):
    order_id: str
    cancel_message: str
