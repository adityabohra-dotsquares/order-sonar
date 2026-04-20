from typing import Optional, Dict, Any
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from models.activity_log import OrderActivityLog
from models.background_tasks import BackgroundTask
from service.order_base_service import OrderBaseService
from fastapi import HTTPException

class UtilityService(OrderBaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # --- Activity Logs ---

    async def list_activity_logs(
        self, page: int = 1, limit: int = 25, order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        stmt = select(OrderActivityLog)
        count_stmt = select(func.count()).select_from(OrderActivityLog)

        if order_id:
            stmt = stmt.where(OrderActivityLog.order_id == order_id)
            count_stmt = count_stmt.where(OrderActivityLog.order_id == order_id)

        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(desc(OrderActivityLog.created_at)).limit(limit).offset((page - 1) * limit)
        
        result = await self.db.execute(stmt)
        logs = result.scalars().all()

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if limit > 0 else 0,
            "data": [
                {
                    "entity_type": "order",
                    "entity_id": log.order_id,
                    "action": log.action,
                    "status_from": log.status_from,
                    "status_to": log.status_to,
                    "description": log.description,
                    "performed_by": log.user_id or "SYSTEM",
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
        }

    # --- Background Tasks ---

    async def list_background_tasks(
        self, page: int = 1, page_size: int = 10, task_type: Optional[str] = None, status: Optional[str] = None
    ) -> Dict[str, Any]:
        query = select(BackgroundTask)
        
        if task_type:
            query = query.where(BackgroundTask.task_type == task_type)
        if status:
            query = query.where(BackgroundTask.status == status)
        
        count_query = select(func.count()).select_from(query.subquery())
        total_res = await self.db.execute(count_query)
        total = total_res.scalar() or 0
        
        query = query.order_by(desc(BackgroundTask.created_at)).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        tasks = result.scalars().all()
        
        return {
            "total": total,
            "tasks": tasks
        }

    async def get_background_task_details(self, task_id: str) -> BackgroundTask:
        stmt = select(BackgroundTask).where(BackgroundTask.id == task_id)
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return task
