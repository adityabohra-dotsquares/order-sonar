from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.order_number_config import OrderNumberConfig
from schemas.order_number_config import OrderNumberConfigUpdate
from service.order_base_service import OrderBaseService
from fastapi import HTTPException

class ConfigService(OrderBaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_order_number_config(self) -> OrderNumberConfig:
        """Fetch the order number configuration."""
        result = await self.db.execute(select(OrderNumberConfig).limit(1))
        config = result.scalars().first()
        if not config:
            raise HTTPException(status_code=404, detail="Order number configuration not initialized yet.")
        return config

    async def update_order_number_config(self, config_in: OrderNumberConfigUpdate) -> OrderNumberConfig:
        """Update or create the order number configuration."""
        result = await self.db.execute(select(OrderNumberConfig).limit(1))
        config = result.scalars().first()
        
        if not config:
            # Create it if it doesn't exist
            config = OrderNumberConfig(**config_in.model_dump())
            self.db.add(config)
        else:
            update_data = config_in.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(config, field, value)
        
        await self.db.commit()
        await self.db.refresh(config)
        return config
