from dataclasses import dataclass
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field


@dataclass
class PaginationParams:
    """Зависимость FastAPI для параметров пагинации (page, page_size)."""
    page: Annotated[int, Query(ge=1, description='Номер страницы')] = 1
    page_size: Annotated[int, Query(ge=1, le=100, description='Размер страницы')] = 20


class Pagination(BaseModel):
    """Метаданные пагинации."""
    page: int
    page_size: int
    total: int
    total_pages: int


def make_pagination(total: int, page: int, page_size: int) -> Pagination:
    """Сформировать Pagination по общему количеству и параметрам страницы."""
    total_pages = max(1, (total + page_size - 1) // page_size)
    return Pagination(page=page, page_size=page_size, total=total, total_pages=total_pages)


class MessageResponse(BaseModel):
    """Универсальный ответ для операций без тела."""
    message: str = Field(..., description='Человекочитаемое сообщение')
