from typing import Generic, TypeVar, List
from pydantic import BaseModel

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    page: int
    limit: int
    total: int
    pages: int
    data: List[T]
