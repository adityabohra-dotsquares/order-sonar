import io
import re
import uuid
import asyncio
import pandas as pd
import numpy as np
from typing import Dict, Any
from sqlalchemy import select, and_, text, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.mysql import insert
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from loguru import logger
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from models.shipping_rules import DeliveryZone, PostcodeZone, RateByZone
from models.background_tasks import BackgroundTask
from models.orders import Order, OrderDetails, OrderItem, OrderStatus
from schemas.import_export import ProductZoneRateTemplateRequest
from service.order_base_service import OrderBaseService
from utils.api_calling import fetch_skus_from_product_service, validate_skus_with_product_service

class ImportExportService(OrderBaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.INVALID_EXCEL_MSG = "Invalid Excel file"

    # --- Utility Methods ---
    def _safe_get(self, obj, attr, default=""):
        if obj is None:
            return default
        return getattr(obj, attr, default)

    def _created_at_date(self, created_at):
        if created_at is None:
            return ""
        return created_at.strftime("%d-%m-%Y")

    def _created_at_time(self, created_at):
        if created_at is None:
            return ""
        return created_at.strftime("%I:%M:%S %p")

    def _promotion_status(self, order: Order):
        if order.discount_amount and order.discount_amount > 0:
            return "Yes"
        return "No"

    # --- Zone Import/Export ---

    async def import_zones(self, file: UploadFile, dry_run: bool = False) -> Dict[str, Any]:
        try:
            df = pd.read_excel(file.file)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=self.INVALID_EXCEL_MSG)

        required_cols = {"zone_name", "zone_code"}
        if not required_cols.issubset(df.columns):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Excel must contain columns: {required_cols}",
            )

        errors = []
        success_rows = 0

        async with self.db.begin():
            for index, row in df.iterrows():
                try:
                    zone_name = str(row["zone_name"]).strip()
                    zone_code = str(row["zone_code"]).strip()

                    if not zone_name or not zone_code:
                        raise ValueError("Missing zone_name or zone_code")

                    result = await self.db.execute(
                        select(DeliveryZone).where(
                            and_(
                                DeliveryZone.zone_code == zone_code,
                                DeliveryZone.zone_name == zone_name,
                            )
                        )
                    )
                    zone = result.scalar_one_or_none()

                    if not zone:
                        self.db.add(
                            DeliveryZone(
                                zone_code=zone_code,
                                zone_name=zone_name,
                                is_active=True,
                            )
                        )
                    else:
                        zone.is_active = True
                    success_rows += 1

                except Exception as row_error:
                    errors.append({"row": index + 2, "error": str(row_error)})

            if dry_run:
                await self.db.rollback()
                return {"dry_run": True, "success_rows": success_rows, "errors": errors}

        return {"dry_run": False, "success_rows": success_rows, "errors": errors}

    async def export_zones(self, format: str = "excel") -> StreamingResponse:
        result = await self.db.execute(
            select(DeliveryZone.zone_name, DeliveryZone.zone_code).order_by(DeliveryZone.zone_code)
        )
        rows = result.all()
        df = pd.DataFrame(rows, columns=["zone_name", "zone_code"])

        if format == "csv":
            buffer = io.StringIO()
            df.to_csv(buffer, index=False)
            buffer.seek(0)
            return StreamingResponse(
                io.BytesIO(buffer.getvalue().encode()),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=delivery_zones.csv"},
            )

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Zones", index=False)
            worksheet = writer.sheets["Zones"]
            bold_font = Font(bold=True)
            for cell in worksheet[1]:
                cell.font = bold_font
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=delivery_zones.xlsx"},
        )

    # --- Postcode Import/Export ---

    async def import_postcodes(self, file: UploadFile, dry_run: bool = False) -> Dict[str, Any]:
        try:
            df = pd.read_excel(file.file)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=self.INVALID_EXCEL_MSG)

        required_cols = {"postcode", "zone_code"}
        if not required_cols.issubset(df.columns):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Excel must contain columns: {required_cols}",
            )

        parsed_rows = []
        unique_search_codes = set()
        for index, row in df.iterrows():
            raw_zc = str(row.get("zone_code", "")).strip()
            raw_pc = str(row.get("postcode", "")).strip()
            if not raw_zc or raw_zc.lower() == "nan":
                parsed_rows.append({"index": index, "error": "Missing zone_code"})
                continue
            if not raw_pc or raw_pc.lower() == "nan":
                parsed_rows.append({"index": index, "error": "Missing postcode"})
                continue

            match = re.search(r"^(.*)\((.*)\)$", raw_zc)
            z_name = match.group(1).strip() if match else None
            z_code = match.group(2).strip() if match else raw_zc
            unique_search_codes.add(z_code)
            parsed_rows.append({
                "index": index, "postcode": raw_pc, "search_code": z_code,
                "search_name": z_name, "original_zone_str": raw_zc
            })

        zone_res = await self.db.execute(select(DeliveryZone).where(DeliveryZone.zone_code.in_(unique_search_codes)))
        zones = zone_res.scalars().all()
        zone_candidates_map = {}
        for z in zones:
            if z.zone_code not in zone_candidates_map:
                zone_candidates_map[z.zone_code] = []
            zone_candidates_map[z.zone_code].append(z)

        errors = []
        success_rows = 0
        async with self.db.begin():
            for row_data in parsed_rows:
                index = row_data["index"]
                if "error" in row_data:
                    errors.append({"row": index + 2, "error": row_data["error"]})
                    continue
                try:
                    candidates = zone_candidates_map.get(row_data["search_code"], [])
                    if not candidates:
                        raise ValueError(f"Zone code '{row_data['search_code']}' not found")
                    
                    final_match = None
                    if row_data["search_name"]:
                        filtered = [z for z in candidates if z.zone_name == row_data["search_name"]]
                        if not filtered:
                            raise ValueError(f"Zone name mismatch for code '{row_data['search_code']}'")
                        final_match = filtered[0]
                    else:
                        if len(candidates) > 1:
                            raise ValueError(f"Ambiguous code '{row_data['search_code']}'. Use Name(Code) format.")
                        final_match = candidates[0]

                    mapping_res = await self.db.execute(select(PostcodeZone).where(PostcodeZone.postcode == row_data["postcode"]))
                    mapping = mapping_res.scalar_one_or_none()
                    if mapping:
                        mapping.zone_id = final_match.id
                    else:
                        self.db.add(PostcodeZone(postcode=row_data["postcode"], zone_id=final_match.id))
                    success_rows += 1
                except Exception as e:
                    errors.append({"row": index + 2, "error": str(e)})

            if dry_run:
                await self.db.rollback()
                return {"dry_run": True, "success_rows": success_rows, "errors": errors}

        return {"dry_run": False, "success_rows": success_rows, "errors": errors}

    async def export_postcode_template(self) -> StreamingResponse:
        result = await self.db.execute(
            select(PostcodeZone.postcode, DeliveryZone.zone_code, DeliveryZone.zone_name)
            .join(DeliveryZone, PostcodeZone.zone_id == DeliveryZone.id)
            .order_by(PostcodeZone.postcode)
        )
        rows = result.all()
        data = [{"postcode": r.postcode, "zone_code": f"{r.zone_name}({r.zone_code})"} for r in rows]
        df = pd.DataFrame(data, columns=["postcode", "zone_code"]) if data else pd.DataFrame(columns=["postcode", "zone_code"])

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="postcodes")
            workbook = writer.book
            worksheet = writer.sheets["postcodes"]
            header_format = workbook.add_format({"bold": True, "border": 1, "align": "center"})
            for col_num, column_name in enumerate(df.columns):
                worksheet.write(0, col_num, column_name, header_format)
            worksheet.set_column("A:A", 15)
            worksheet.set_column("B:B", 30)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=postcode_template.xlsx"},
        )

    # --- Product Zone Rates Import/Export ---

    async def process_background_import_product_zone_rates(
        self, file_content: bytes, filename: str, dry_run: bool, task_id: str
    ):
        """
        Background task to process product zone rate imports with persistent status tracking.
        """
        import time
        from database import async_session

        start_total = time.time()
        logger.info(f"Background total timing started for {filename}")
        
        # Use a fresh session for this background logic to avoid issues with parent session
        async with async_session() as db:
            # Update status to processing
            task_obj = None
            try:
                task_res = await db.execute(select(BackgroundTask).where(BackgroundTask.id == task_id))
                task_obj = task_res.scalar_one_or_none()
                if task_obj:
                    task_obj.status = "processing"
                    await db.commit()
            except Exception as e:
                logger.error(f"Error updating task status to processing: {e}")

            # Named Lock to prevent concurrent imports
            lock_name = "lock_import_product_zone_rates"
            try:
                lock_res = await db.execute(
                    text("SELECT GET_LOCK(:lock_name, 5)"), {"lock_name": lock_name}
                )
                if not lock_res.scalar():
                    logger.warning(f"Could not acquire lock for {lock_name}.")
                    if task_obj:
                        task_obj.status = "failed"
                        task_obj.task_info = {"error": "Another import process is already running."}
                        await db.commit()
                    return
            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")

            errors = []
            success_rows = 0
            completed_count = 0
            last_update_time = time.time()

            try:
                # 1. Read Excel
                try:
                    df = pd.read_excel(io.BytesIO(file_content))
                    df.columns = df.columns.astype(str)
                except Exception as e:
                    logger.error(f"Invalid Excel in background: {e}")
                    if task_obj:
                        task_obj.status = "failed"
                        task_obj.task_info = {"error": f"Invalid Excel: {str(e)}"}
                        await db.commit()
                    return

                sku_col = next((col for col in df.columns if col.lower() == "sku"), None)
                if not sku_col:
                    if task_obj:
                        task_obj.status = "failed"
                        task_obj.task_info = {"error": "Excel must contain 'sku' column."}
                        await db.commit()
                    return
                df.rename(columns={sku_col: "sku"}, inplace=True)

                # 2. Identify Zone Columns
                result = await db.execute(select(DeliveryZone).where(DeliveryZone.is_active == True))
                db_zone_map = {}
                for z in result.scalars().all():
                    if z.zone_code not in db_zone_map: db_zone_map[z.zone_code] = []
                    db_zone_map[z.zone_code].append(z)

                col_to_zone_ids_map = {}
                valid_zone_codes = set()
                for col in df.columns:
                    if col == "sku": continue
                    match = re.search(r"^(.*)\((.*)\)$", col)
                    code = match.group(2).strip() if match else col.strip()
                    name = match.group(1).strip() if match else None
                    zones = db_zone_map.get(code)
                    if zones:
                        target_zone_ids = [z.id for z in zones if (not name or z.zone_name == name)]
                        if target_zone_ids:
                            col_to_zone_ids_map[col] = target_zone_ids
                            valid_zone_codes.add(code)

                if not valid_zone_codes:
                    if task_obj:
                        task_obj.status = "completed"
                        task_obj.task_info = {"warning": "No valid zone columns found."}
                        await db.commit()
                    return

                # 3. Validate SKUs
                grouped = df.groupby("sku")
                sku_list = list(grouped.groups.keys())
                all_skus = [str(s).strip() for s in sku_list if str(s).strip()]
                if not all_skus:
                    if task_obj:
                        task_obj.status = "completed"; await db.commit()
                    return

                sku_validation = await validate_skus_with_product_service(all_skus)
                all_zone_ids = list(set(id for ids in col_to_zone_ids_map.values() for id in ids))

                # 4. Batch Process
                BATCH_SIZE = 200
                semaphore = asyncio.Semaphore(3)
                progress_lock = asyncio.Lock()

                async def _process_batch(batch_skus):
                    nonlocal success_rows, errors, completed_count, last_update_time
                    async with semaphore:
                        batch_errors = []
                        local_success = 0
                        async with async_session() as db_batch:
                            batch_stmt = select(RateByZone).where(
                                RateByZone.product_identifier.in_(batch_skus),
                                RateByZone.zone_id.in_(all_zone_ids),
                            )
                            batch_res = await db_batch.execute(batch_stmt)
                            batch_rate_objs = {(r.product_identifier, r.zone_id): r for r in batch_res.scalars().all()}

                            batch_upsert_data = []
                            for sku in batch_skus:
                                sku_rows = grouped.get_group(sku)
                                sku_str = str(sku).strip()
                                if not sku_validation.get(sku_str):
                                    for idx in sku_rows.index:
                                        batch_errors.append({"row": int(idx) + 2, "error": f"SKU not found: {sku_str}"})
                                    continue

                                for index, row in sku_rows.to_dict("index").items():
                                    for col_name, zone_ids in col_to_zone_ids_map.items():
                                        rate_val = row.get(col_name)
                                        if pd.isna(rate_val): continue
                                        try:
                                            rate_str = str(rate_val).strip()
                                            if not rate_str: continue
                                            float(rate_str)
                                        except ValueError:
                                            batch_errors.append({"row": int(index) + 2, "column": col_name, "error": f"Invalid rate: {rate_val}"})
                                            continue

                                        for zone_id in zone_ids:
                                            existing_obj = batch_rate_objs.get((sku_str, zone_id))
                                            item_data = {
                                                "product_identifier": sku_str, "zone_id": zone_id, "rate": rate_str,
                                                "is_active": True, "is_shipping_allowed": True
                                            }
                                            item_data["id"] = existing_obj.id if existing_obj else str(uuid.uuid4())
                                            batch_upsert_data.append(item_data)
                                local_success += 1

                            if batch_upsert_data and not dry_run:
                                stmt = insert(RateByZone).values(batch_upsert_data)
                                stmt = stmt.on_duplicate_key_update(
                                    rate=stmt.inserted.rate, is_active=stmt.inserted.is_active, updated_at=func.now()
                                )
                                await db_batch.execute(stmt); await db_batch.commit()

                        async with progress_lock:
                            success_rows += local_success; errors.extend(batch_errors); completed_count += len(batch_skus)
                            if (time.time() - last_update_time) >= 3.0:
                                last_update_time = time.time()
                                try:
                                    # Update BackgroundTask status via a separate connection
                                    async with async_session() as db_prog:
                                        update_stmt = update(BackgroundTask).where(BackgroundTask.id == task_id).values(
                                            task_info={"processed": completed_count, "total": len(sku_list), "success_rows": success_rows, "errors_count": len(errors[:500])}
                                        )
                                        await db_prog.execute(update_stmt); await db_prog.commit()
                                except Exception as e: logger.error(f"Progress update error: {e}")

                tasks = [_process_batch(sku_list[i : i + BATCH_SIZE]) for i in range(0, len(sku_list), BATCH_SIZE)]
                await asyncio.gather(*tasks)

                if task_obj:
                    # Final update
                    async with async_session() as db_final:
                        update_stmt = update(BackgroundTask).where(BackgroundTask.id == task_id).values(
                            status="completed",
                            task_info={"total": len(sku_list), "success_rows": success_rows, "processed": success_rows + len(errors), "errors_count": len(errors), "errors_sample": errors[:100]}
                        )
                        await db_final.execute(update_stmt); await db_final.commit()

            except Exception as e:
                logger.error(f"Background import terminal error: {e}")
                if task_obj:
                    async with async_session() as db_err:
                        update_stmt = update(BackgroundTask).where(BackgroundTask.id == task_id).values(status="failed", task_info={"error": str(e)})
                        await db_err.execute(update_stmt); await db_err.commit()
            finally:
                try:
                    await db.execute(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": lock_name},
                    )
                    await db.commit()
                except Exception as e: logger.error(f"Lock release error: {e}")

    async def import_product_zone_rates(self, file: UploadFile, dry_run: bool = False) -> Dict[str, Any]:
        try:
            file_content = await file.read()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read upload file: {e}")

        new_task = BackgroundTask(
            task_type="product_zone_rate_import",
            status="queued",
            file_url=file.filename,
            task_info={"dry_run": dry_run},
        )
        self.db.add(new_task)
        await self.db.commit()
        await self.db.refresh(new_task)

        from utils.gcp_bucket import upload_file_to_gcs
        try:
            blob_name = f"imports/{uuid.uuid4()}_{file.filename}"
            file_url = upload_file_to_gcs(
                file_bytes=file_content,
                content_type=file.content_type,
                blob_name=blob_name,
            )
            new_task.file_url = file_url
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to upload file to GCS: {e}")
            new_task.status = "failed"
            new_task.task_info = {"error": f"Failed to upload to GCS: {str(e)}"}
            await self.db.commit()
            raise HTTPException(status_code=500, detail="Failed to stage file for processing")

        try:
            from apis.v1.tasks import import_product_zone_rates_task
            import_product_zone_rates_task.delay(file_url, dry_run, new_task.id)
        except Exception as e:
            logger.error(f"Failed to trigger Celery task: {e}")
            new_task.status = "failed"
            new_task.task_info = {"error": f"Failed to queue task: {str(e)}"}
            await self.db.commit()
            raise HTTPException(status_code=500, detail="Failed to queue import task")

        return {
            "status": "Accepted",
            "task_id": new_task.id,
            "message": f"Import of '{file.filename}' has been queued via Celery.",
            "dry_run": dry_run,
        }

    async def export_product_zone_rates_template(self, payload: ProductZoneRateTemplateRequest) -> StreamingResponse:
        zone_result = await self.db.execute(
            select(DeliveryZone.id, DeliveryZone.zone_code, DeliveryZone.zone_name)
            .where(DeliveryZone.is_active == True)
            .order_by(DeliveryZone.zone_code)
        )
        zones = zone_result.all()

        if payload.export_all:
            sku_res = await self.db.execute(select(RateByZone.product_identifier).distinct())
            skus = list(sku_res.scalars().all())
        else:
            if not payload.product_ids:
                skus = []
            else:
                try:
                    skus = await fetch_skus_from_product_service(payload.product_ids)
                except Exception:
                    raise HTTPException(status_code=502, detail="Failed to fetch SKUs from product service")

        rate_map = {}
        if skus and zones:
            zone_ids = [z.id for z in zones]
            rate_res = await self.db.execute(
                select(RateByZone.product_identifier, RateByZone.zone_id, RateByZone.rate)
                .where(RateByZone.product_identifier.in_(skus), RateByZone.zone_id.in_(zone_ids))
            )
            rate_map = {(r.product_identifier, r.zone_id): r.rate for r in rate_res.all()}

        df = pd.DataFrame({"sku": skus})
        for z_id, z_code, z_name in zones:
            header = f"{z_name}({z_code})"
            df[header] = [rate_map.get((sku, z_id), "") for sku in skus]

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Template", index=False)
            worksheet = writer.sheets["Template"]
            bold_font = Font(bold=True)
            for cell in worksheet[1]:
                cell.font = bold_font
            for col_idx, col_name in enumerate(df.columns, start=1):
                worksheet.column_dimensions[get_column_letter(col_idx)].width = max(len(col_name) + 4, 15)
            worksheet.freeze_panes = "A2"
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=product_zone_rate_template.xlsx"},
        )

    # --- Order Import/Export ---

    async def import_orders(self, file: UploadFile, dry_run: bool = False) -> Dict[str, Any]:
        try:
            df = pd.read_excel(file.file)
            df = df.replace({np.nan: None})
        except Exception:
            raise HTTPException(status_code=400, detail=self.INVALID_EXCEL_MSG)

        required_cols = {"Order ID", "SKU", "Qty"}
        if not required_cols.issubset(df.columns):
            raise HTTPException(status_code=400, detail=f"Excel must contain columns: {required_cols}")

        errors = []
        success_rows = 0
        async with self.db.begin():
            grouped = df.groupby("Order ID")
            for order_id_val, group in grouped:
                try:
                    order_num = str(order_id_val).strip()
                    if not order_num: continue
                    first_row = group.iloc[0]
                    
                    res = await self.db.execute(select(Order).options(selectinload(Order.items)).where(Order.order_number == order_num))
                    order = res.scalar_one_or_none()

                    def get_val(row, col):
                        v = row.get(col)
                        return str(v).strip() if v is not None else ""

                    if not order:
                        order = Order(
                            order_number=order_num, brand=get_val(first_row, "Brand Name"),
                            subtotal=0.0, total_amount=0.0, status=OrderStatus.PENDING,
                            notes=get_val(first_row, "Buyer Note")
                        )
                        status_str = get_val(first_row, "Status").lower()
                        for s in OrderStatus:
                            if s.value == status_str:
                                order.status = s; break
                        self.db.add(order)
                        await self.db.flush()

                        details = OrderDetails(
                            order_id=order.id, customer_name=get_val(first_row, "Full Name"),
                            customer_email=get_val(first_row, "Email ID"), customer_phone=get_val(first_row, "Phone number"),
                            shipping_first_name=get_val(first_row, "First Name"), shipping_last_name=get_val(first_row, "Last Name"),
                            shipping_address=get_val(first_row, "Address 1"), shipping_apartment=get_val(first_row, "Address 2"),
                            shipping_city=get_val(first_row, "City"), shipping_state=get_val(first_row, "State"),
                            shipping_postal_code=get_val(first_row, "Zipcode"), shipping_country=get_val(first_row, "Country")
                        )
                        self.db.add(details)
                    else:
                        if get_val(first_row, "Status"):
                            status_str = get_val(first_row, "Status").lower()
                            for s in OrderStatus:
                                if s.value == status_str:
                                    order.status = s; break

                    current_items = {item.sku: item for item in order.items} if order.items else {}
                    order_subtotal = 0.0
                    for idx, row in group.iterrows():
                        sku = get_val(row, "SKU")
                        if not sku: continue
                        qty = int(row.get("Qty") or 1)
                        u_price = float(row.get("Unit Price") or 0.0)
                        t_price = qty * u_price
                        order_subtotal += t_price
                        if sku in current_items:
                            item = current_items[sku]
                            item.quantity, item.unit_price, item.total_price = qty, u_price, t_price
                            item.name = get_val(row, "Item name")
                        else:
                            self.db.add(OrderItem(
                                order_id=order.id, product_id=sku, sku=sku, name=get_val(row, "Item name"),
                                quantity=qty, unit_price=u_price, total_price=t_price, status=order.status
                            ))
                    
                    order.subtotal = order_subtotal
                    order.shipping_cost = float(first_row.get("Shipping") or 0.0)
                    order.tax_amount = float(first_row.get("Tax") or 0.0)
                    order.discount_amount = float(first_row.get("Promotion Price") or 0.0)
                    order.total_amount = order.subtotal + order.shipping_cost + order.tax_amount - order.discount_amount
                    success_rows += len(group)
                except Exception as e:
                    errors.append({"order": order_num, "error": str(e)})

            if dry_run:
                await self.db.rollback()
                return {"dry_run": True, "success_rows": success_rows, "errors": errors}

        return {"dry_run": False, "success_rows": success_rows, "errors": errors}

    async def export_orders(self) -> StreamingResponse:
        res = await self.db.execute(
            select(Order).options(selectinload(Order.order_details), selectinload(Order.items)).order_by(Order.created_at.desc())
        )
        orders = res.scalars().all()
        export_data = []

        field_map = {
            "Order ID": lambda o, d: o.order_number,
            "Brand Name": lambda o, d: o.brand,
            "First Name": lambda o, d: self._safe_get(d, "shipping_first_name"),
            "Last Name": lambda o, d: self._safe_get(d, "shipping_last_name"),
            "Full Name": lambda o, d: self._safe_get(d, "customer_name"),
            "Phone number": lambda o, d: self._safe_get(d, "customer_phone"),
            "Email ID": lambda o, d: self._safe_get(d, "customer_email"),
            "Address 1": lambda o, d: self._safe_get(d, "shipping_address"),
            "Address 2": lambda o, d: self._safe_get(d, "shipping_apartment"),
            "City": lambda o, d: self._safe_get(d, "shipping_city"),
            "State": lambda o, d: self._safe_get(d, "shipping_state"),
            "Zipcode": lambda o, d: self._safe_get(d, "shipping_postal_code"),
            "Country": lambda o, d: self._safe_get(d, "shipping_country"),
            "Shipping": lambda o, d: o.shipping_cost,
            "Tax": lambda o, d: o.tax_amount,
            "Total Price": lambda o, d: o.total_amount,
            "Promotion (Yes/No)": lambda o, d: self._promotion_status(o),
            "Promotion Code": lambda o, d: "",
            "Promotion %": lambda o, d: 0,
            "Promotion Price": lambda o, d: o.discount_amount,
            "Tracking #": lambda o, d: o.tracking_number,
            "Carrier": lambda o, d: o.courier,
            "Carrier Code": lambda o, d: "",
            "Tracking Link": lambda o, d: "",
            "Buyer Note": lambda o, d: o.notes,
            "Status": lambda o, d: self._safe_get(o, "status")
        }

        for order in orders:
            d = order.order_details
            base_row = {
                "Date(DD-MM-YYYY)": self._created_at_date(order.created_at),
                "Time(hh:mm:ss:)(AM/PM)": self._created_at_time(order.created_at),
                **{k: fn(order, d) for k, fn in field_map.items()}
            }
            if not order.items:
                export_data.append(base_row)
            else:
                for item in order.items:
                    row = base_row.copy()
                    row.update({
                        "SKU": item.sku, "Item name": item.name, "Item weight (kg)": "",
                        "Qty": item.quantity, "Unit Price": item.unit_price, "Sale Price": item.unit_price
                    })
                    export_data.append(row)

        df = pd.DataFrame(export_data)
        expected_cols = [
            "Date(DD-MM-YYYY)", "Time(hh:mm:ss:)(AM/PM)", "Order ID", "First Name", "Last Name", "Full Name",
            "Brand Name", "Address 1", "Address 2", "City", "State", "Zipcode", "Country", "Phone number", "Email ID",
            "SKU", "Item name", "Item weight (kg)", "Qty", "Unit Price", "Sale Price", "Promotion %", "Promotion Price",
            "Shipping", "Tax", "Total Price", "Promotion (Yes/No)", "Promotion Code", "Tracking #", "Carrier",
            "Carrier Code", "Tracking Link", "Buyer Note", "Status"
        ]
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
        df = df[expected_cols]

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Orders", index=False)
            worksheet = writer.sheets["Orders"]
            for cell in worksheet[1]: cell.font = Font(bold=True)
        buffer.seek(0)
        return StreamingResponse(
            buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=orders_export.xlsx"}
        )
