from pydantic import BaseModel
from typing import List


class ProductZoneRateTemplateRequest(BaseModel):
    product_ids: List[str] = []
    export_all: bool = False
