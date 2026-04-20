from typing import Optional
from sqlalchemy import select, and_, or_, func, delete
from sqlalchemy.orm import joinedload
from models.shipping_rules import DeliveryZone, PostcodeZone, RateByZone
from schemas.delivery_zones import DeliveryZoneCreate
from schemas.postcode_zones import PostcodeZoneCreate
from schemas.rate_by_zones import RateByZoneCreate, RateByZoneUpdate
from service.order_base_service import OrderBaseService
from utils.api_calling import validate_skus_with_product_service
from utils.redis_client import redis_cache
from utils.constants import messages
from fastapi import HTTPException
import httpx
import json
from fastapi.encoders import jsonable_encoder

class ZoneService(OrderBaseService):
    def __init__(self, db):
        super().__init__(db)

    # --- DeliveryZone CRUD ---

    async def create_delivery_zone(self, payload: DeliveryZoneCreate):
        """Create a Delivery Zone with duplicate check"""
        result = await self.db.execute(
            select(DeliveryZone).where(
                and_(
                    DeliveryZone.zone_code == payload.zone_code,
                    DeliveryZone.zone_name == payload.zone_name,
                )
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"Delivery Zone with code '{payload.zone_code}' and name '{payload.zone_name}' already exists."
            )

        zone = DeliveryZone(
            zone_code=payload.zone_code,
            zone_name=payload.zone_name,
            is_active=payload.is_active,
        )
        self.db.add(zone)
        await self.db.commit()
        await self.db.refresh(zone)
        return zone

    async def update_delivery_zone(self, zone_id: str, payload: DeliveryZoneCreate):
        """Update a Delivery Zone with duplicate check"""
        result = await self.db.execute(select(DeliveryZone).where(DeliveryZone.id == zone_id))
        zone = result.scalar_one_or_none()
        if not zone:
            raise HTTPException(status_code=404, detail="Delivery Zone not found")

        # Duplicate check excluding current zone
        dup_result = await self.db.execute(
            select(DeliveryZone).where(
                and_(
                    DeliveryZone.zone_code == payload.zone_code,
                    DeliveryZone.zone_name == payload.zone_name,
                    DeliveryZone.id != zone_id,
                )
            )
        )
        if dup_result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"Delivery Zone with code '{payload.zone_code}' and name '{payload.zone_name}' already exists."
            )

        zone.zone_code = payload.zone_code
        zone.zone_name = payload.zone_name
        zone.is_active = payload.is_active

        await self.db.commit()
        await self.db.refresh(zone)
        return zone

    async def list_delivery_zones(
        self, page: int = 1, limit: int = 25, search: Optional[str] = None, sort_by: str = "created_at", sort_dir: str = "desc"
    ):
        """List Delivery Zones with pagination and search"""
        stmt = select(DeliveryZone)
        count_stmt = select(func.count()).select_from(DeliveryZone)

        if search:
            search_filter = or_(
                DeliveryZone.zone_code.ilike(f"%{search}%"),
                DeliveryZone.zone_name.ilike(f"%{search}%"),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        # Sorting
        if hasattr(DeliveryZone, sort_by):
            column = getattr(DeliveryZone, sort_by)
            stmt = stmt.order_by(column.desc() if sort_dir.lower() == "desc" else column.asc())
        else:
            stmt = stmt.order_by(DeliveryZone.created_at.desc())

        total = (await self.db.execute(count_stmt)).scalar() or 0
        
        if limit == -1:
            items_result = await self.db.execute(stmt)
            return items_result.scalars().all(), total, 1, total
        
        offset = (page - 1) * limit
        items_result = await self.db.execute(stmt.offset(offset).limit(limit))
        pages = (total + limit - 1) // limit if limit > 0 else 0
        return items_result.scalars().all(), total, pages, limit

    async def get_delivery_zone(self, zone_id: str):
        """Get Delivery Zone or raise 404"""
        result = await self.db.execute(select(DeliveryZone).where(DeliveryZone.id == zone_id))
        zone = result.scalar_one_or_none()
        if not zone:
            raise HTTPException(status_code=404, detail="Delivery Zone not found")
        return zone

    async def delete_delivery_zone(self, zone_id: str):
        """Delete Delivery Zone with error handling for associations"""
        zone = await self.get_delivery_zone(zone_id)
        try:
            await self.db.delete(zone)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Delivery Zone cannot be deleted as it is associated with some data"
            )

    # --- PostcodeZone CRUD ---

    async def create_postcode_zone(self, payload: PostcodeZoneCreate):
        """Create mapping between postcode and zone"""
        # Validate Zone Exists
        zone = await self.get_delivery_zone(payload.zone_code)
        
        # Check duplicate mapping
        result = await self.db.execute(
            select(PostcodeZone).where(
                and_(
                    PostcodeZone.postcode == payload.postcode,
                    PostcodeZone.zone_id == payload.zone_code,
                )
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=messages.get("postcode_zone_combination_exists").format(
                    postcode=payload.postcode,
                    zone_code=f"{zone.zone_code}-{zone.zone_name}"
                )
            )

        mapping = PostcodeZone(postcode=payload.postcode, zone_id=payload.zone_code)
        self.db.add(mapping)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail="Database error creating mapping")
        
        # Re-fetch with relationship
        res = await self.db.execute(
            select(PostcodeZone).options(joinedload(PostcodeZone.zone)).where(PostcodeZone.id == mapping.id)
        )
        return res.scalar_one()

    async def list_postcode_zones(
        self, page: int = 1, limit: int = 25, search: Optional[str] = None, sort_by: str = "created_at", sort_dir: str = "desc"
    ):
        """List Postcode-Zone mappings with pagination and search"""
        stmt = select(PostcodeZone).options(joinedload(PostcodeZone.zone))
        count_stmt = select(func.count()).select_from(PostcodeZone)

        if search:
            search_filter = or_(
                PostcodeZone.postcode.ilike(f"%{search}%"),
                DeliveryZone.zone_code.ilike(f"%{search}%"),
                DeliveryZone.zone_name.ilike(f"%{search}%")
            )
            stmt = stmt.join(DeliveryZone).where(search_filter)
            count_stmt = count_stmt.join(DeliveryZone).where(search_filter)

        if hasattr(PostcodeZone, sort_by):
            column = getattr(PostcodeZone, sort_by)
            stmt = stmt.order_by(column.desc() if sort_dir.lower() == "desc" else column.asc())
        else:
            stmt = stmt.order_by(PostcodeZone.created_at.desc())

        total = (await self.db.execute(count_stmt)).scalar() or 0
        
        if limit == -1:
            items_result = await self.db.execute(stmt)
            return items_result.scalars().all(), total, 1, total

        offset = (page - 1) * limit
        items_result = await self.db.execute(stmt.offset(offset).limit(limit))
        pages = (total + limit - 1) // limit if limit > 0 else 0
        return items_result.scalars().all(), total, pages, limit

    async def delete_postcode_zone(self, mapping_id: str):
        """Delete mapping"""
        result = await self.db.execute(select(PostcodeZone).where(PostcodeZone.id == mapping_id))
        mapping = result.scalar_one_or_none()
        if not mapping:
            raise HTTPException(status_code=404, detail="Postcode Zone mapping not found")
        await self.db.delete(mapping)
        await self.db.commit()

    async def delete_all_postcode_zones(self):
        """Delete all mappings"""
        await self.db.execute(delete(PostcodeZone))
        await self.db.commit()

    # --- RateByZone CRUD ---

    async def create_rate_by_zone(self, payload: RateByZoneCreate):
        """Create shipping rate for product in zone with SKU validation"""
        # SKU validation
        try:
            sku_val = await validate_skus_with_product_service([payload.product_identifier])
            if not sku_val.get(payload.product_identifier):
                raise HTTPException(status_code=400, detail=f"SKU '{payload.product_identifier}' not found.")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Product service unavailable: {str(e)}")

        # Zone validation
        zone = await self.get_delivery_zone(payload.zone_code)

        # Duplicate check
        res = await self.db.execute(
            select(RateByZone).where(
                and_(RateByZone.product_identifier == payload.product_identifier, RateByZone.zone_id == zone.id)
            )
        )
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Mapping for product and zone already exists.")

        rate_obj = RateByZone(
            product_identifier=payload.product_identifier,
            zone_id=zone.id,
            rate=str(float(payload.rate)) if payload.rate is not None else None,
            is_active=payload.is_active,
        )
        self.db.add(rate_obj)
        await self.db.commit()
        await self.db.refresh(rate_obj)
        rate_obj.zone = zone
        
        await redis_cache.delete_by_prefix("rates_by_zone:")
        return rate_obj

    async def list_rates_by_zone(
        self, zone_code: Optional[str] = None, product_identifier: Optional[str] = None,
        page: int = 1, limit: int = 25, sort_by: str = "created_at", sort_dir: str = "desc"
    ):
        """List rates with caching and filters"""
        cache_key = f"rates_by_zone:list:zc={zone_code}:pi={product_identifier}:p={page}:l={limit}:sb={sort_by}:sd={sort_dir}"
        cached = await redis_cache.get(cache_key)
        if cached:
            return json.loads(cached)

        stmt = select(RateByZone).options(joinedload(RateByZone.zone))
        count_stmt = select(func.count()).select_from(RateByZone)

        if zone_code:
            stmt = stmt.where(RateByZone.zone_id == zone_code)
            count_stmt = count_stmt.where(RateByZone.zone_id == zone_code)
        if product_identifier:
            stmt = stmt.where(RateByZone.product_identifier == product_identifier)
            count_stmt = count_stmt.where(RateByZone.product_identifier == product_identifier)

        if hasattr(RateByZone, sort_by):
            column = getattr(RateByZone, sort_by)
            stmt = stmt.order_by(column.desc() if sort_dir.lower() == "desc" else column.asc())
        else:
            stmt = stmt.order_by(RateByZone.created_at.desc())

        total = (await self.db.execute(count_stmt)).scalar() or 0
        
        if limit == -1:
            offset = 0
            res_limit = total
            pages = 1
        else:
            offset = (page - 1) * limit
            stmt = stmt.limit(limit).offset(offset)
            res_limit = limit
            pages = (total + limit - 1) // limit if limit > 0 else 0

        result = await self.db.execute(stmt)
        rates = result.scalars().all()
        
        from schemas.rate_by_zones import RateByZoneOut
        data = [RateByZoneOut.model_validate(r).model_dump() for r in rates]
        response = {"page": page, "limit": res_limit, "total": total, "pages": pages, "data": data}

        await redis_cache.set(cache_key, json.dumps(jsonable_encoder(response)), ex=300)
        return response

    async def update_rate_by_zone(self, rate_id: str, payload: RateByZoneUpdate):
        """Update rate details"""
        result = await self.db.execute(
            select(RateByZone).options(joinedload(RateByZone.zone)).where(RateByZone.id == rate_id)
        )
        rate_obj = result.scalar_one_or_none()
        if not rate_obj:
            raise HTTPException(status_code=404, detail="Rate mapping not found")

        if payload.rate is not None:
            rate_obj.rate = str(float(payload.rate))
        if payload.is_active is not None:
            rate_obj.is_active = payload.is_active

        current_zone = rate_obj.zone
        await self.db.commit()
        await self.db.refresh(rate_obj)
        rate_obj.zone = current_zone
        
        await redis_cache.delete_by_prefix("rates_by_zone:")
        return rate_obj

    async def delete_rate_by_zone(self, rate_id: str):
        """Delete rate mapping"""
        result = await self.db.execute(select(RateByZone).where(RateByZone.id == rate_id))
        rate_obj = result.scalar_one_or_none()
        if not rate_obj:
            raise HTTPException(status_code=404, detail="Rate mapping not found")
        await self.db.delete(rate_obj)
        await self.db.commit()
        await redis_cache.delete_by_prefix("rates_by_zone:")

    async def delete_all_rates(self):
        """Delete all rates"""
        await self.db.execute(delete(RateByZone))
        await self.db.commit()
        await redis_cache.delete_by_prefix("rates_by_zone:")

    async def list_grouped_rates(
        self, page: int = 1, limit: int = 25, search: Optional[str] = None, sort_by: str = "created_at", sort_dir: str = "desc"
    ):
        """List rates grouped by product with caching"""
        cache_key = f"rates_by_zone:grouped:p={page}:l={limit}:s={search}:sb={sort_by}:sd={sort_dir}"
        cached = await redis_cache.get(cache_key)
        if cached:
            return json.loads(cached)

        distinct_stmt = select(RateByZone.product_identifier).group_by(RateByZone.product_identifier)
        count_stmt = select(func.count(func.distinct(RateByZone.product_identifier)))
        
        if search:
            distinct_stmt = distinct_stmt.where(RateByZone.product_identifier.ilike(f"%{search}%"))
            count_stmt = count_stmt.where(RateByZone.product_identifier.ilike(f"%{search}%"))

        if sort_by == "created_at":
            distinct_stmt = distinct_stmt.order_by(
                func.max(RateByZone.created_at).desc() if sort_dir.lower() == "desc" else func.max(RateByZone.created_at).asc()
            )
        elif sort_by == "product_identifier":
            distinct_stmt = distinct_stmt.order_by(
                RateByZone.product_identifier.desc() if sort_dir.lower() == "desc" else RateByZone.product_identifier.asc()
            )
        else:
            distinct_stmt = distinct_stmt.order_by(func.max(RateByZone.created_at).desc())
            
        total = (await self.db.execute(count_stmt)).scalar() or 0
        
        if limit == -1:
            res_limit = total
            pages = 1
        else:
            offset = (page - 1) * limit
            distinct_stmt = distinct_stmt.limit(limit).offset(offset)
            res_limit = limit
            pages = (total + limit - 1) // limit if limit > 0 else 0

        p_result = await self.db.execute(distinct_stmt)
        products = p_result.scalars().all()
        
        if not products:
            return {"page": page, "limit": res_limit, "total": total, "pages": pages, "data": []}

        rates_stmt = select(RateByZone).options(joinedload(RateByZone.zone)).where(RateByZone.product_identifier.in_(products))
        all_rates = (await self.db.execute(rates_stmt)).scalars().all()
        
        from schemas.rate_by_zones import RateByZoneOut
        grouped = {pid: {"product_identifier": pid, "product_details": {"sku": pid}, "rates": []} for pid in products}
        for rate in all_rates:
            if rate.product_identifier in grouped:
                grouped[rate.product_identifier]["rates"].append(RateByZoneOut.model_validate(rate).model_dump())
                    
        response = {"page": page, "limit": res_limit, "total": total, "pages": pages, "data": list(grouped.values())}
        await redis_cache.set(cache_key, json.dumps(jsonable_encoder(response)), ex=300)
        return response
