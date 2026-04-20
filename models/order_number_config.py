from sqlalchemy import Column, String, Boolean, Integer
from database import Base

class OrderNumberConfig(Base):
    __tablename__ = "order_number_configs"

    id = Column(Integer, primary_key=True, index=True)
    prefix = Column(String(50), nullable=True)
    suffix = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<OrderNumberConfig(prefix='{self.prefix}', suffix='{self.suffix}')>"
