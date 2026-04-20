from pydantic import BaseModel
from typing import Optional, Any, List
from datetime import datetime

class BackgroundTaskBase(BaseModel):
    task_type: Optional[str] = None
    status: Optional[str] = None
    file_url: Optional[str] = None
    task_info: Optional[Any] = None

class BackgroundTaskCreate(BackgroundTaskBase):
    pass

class BackgroundTaskSchema(BackgroundTaskBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    added_by: Optional[str] = None
    updated_by: Optional[str] = None

    class Config:
        from_attributes = True

class BackgroundTaskList(BaseModel):
    total: int
    tasks: List[BackgroundTaskSchema]
