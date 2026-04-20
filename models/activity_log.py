from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from database import Base
import uuid

class OrderActivityLog(Base):
    __tablename__ = "order_activity_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    action = Column(String(100), nullable=False)  # e.g., "Order Created", "Status Changed"
    status_from = Column(String(50), nullable=True)
    status_to = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    user_id = Column(String(36), nullable=True)  # ID of user who performed the action
    created_at = Column(DateTime(timezone=True), server_default=func.now())
