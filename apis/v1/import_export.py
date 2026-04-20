from fastapi import APIRouter, UploadFile, File, Depends, Query
from typing import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from deps import get_db
from schemas.import_export import ProductZoneRateTemplateRequest
from service.import_export_service import ImportExportService

router = APIRouter()

def get_import_export_service(db: Annotated[AsyncSession, Depends(get_db)]):
    return ImportExportService(db)

@router.post(
    "/import-zones",
    responses={
        400: {"description": "Invalid Excel file"},
        500: {"description": "Database error"},
    },
)
async def import_zones(
    file: Annotated[UploadFile, File()] = ...,
    dry_run: Annotated[bool, Query()] = False,
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Import zones from Excel"""
    return await service.import_zones(file, dry_run)

@router.get(
    "/export-zones",
    responses={500: {"description": "Database error"}},
)
async def export_zones(
    format: Annotated[str, Query(enum=["excel", "csv"])] = "excel",
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Export zones as Excel or CSV"""
    return await service.export_zones(format)

@router.post(
    "/import-postcodes",
    responses={
        400: {"description": "Invalid Excel file"},
        500: {"description": "Database error"},
    },
)
async def import_postcodes(
    file: Annotated[UploadFile, File()] = ...,
    dry_run: Annotated[bool, Query()] = False,
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Import postcodes from Excel"""
    return await service.import_postcodes(file, dry_run)

@router.get(
    "/export-postcode-template",
    responses={500: {"description": "Database error"}},
)
async def export_postcode_template(
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Export postcode template"""
    return await service.export_postcode_template()

@router.post(
    "/import-product-zone-rates",
    responses={
        400: {"description": "Could not read upload file"},
        500: {"description": "Failed to stage file for processing"},
    },
)
async def import_product_zone_rates(
    file: Annotated[UploadFile, File()] = ...,
    dry_run: Annotated[bool, Query()] = False,
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Trigger product zone rate import as a background task"""
    return await service.import_product_zone_rates(file, dry_run)

@router.post(
    "/export-product-zone-rates",
    responses={
        500: {"description": "Database error"},
        502: {"description": "Product service error"},
    },
)
async def export_product_zone_rates_template(
    payload: ProductZoneRateTemplateRequest,
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Export product zone rate template with existing rates"""
    return await service.export_product_zone_rates_template(payload)

@router.post(
    "/import-orders",
    responses={
        400: {"description": "Invalid Excel file"},
        500: {"description": "Database error"},
    },
)
async def import_orders(
    file: Annotated[UploadFile, File()] = ...,
    dry_run: Annotated[bool, Query()] = False,
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Import orders from Excel"""
    return await service.import_orders(file, dry_run)

@router.get(
    "/export-orders",
    responses={500: {"description": "Database error"}},
)
async def export_orders(
    service: Annotated[ImportExportService, Depends(get_import_export_service)] = None,
):
    """Export all orders as Excel"""
    return await service.export_orders()
