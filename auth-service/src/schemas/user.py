from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.schemas.role import RoleResponse


class UserResponse(BaseModel):
    id: UUID = Field(..., description="Уникальный идентификатор пользователя")
    login: str = Field(..., description="Логин пользователя")
    first_name: str | None = Field(None, description="Имя")
    last_name: str | None = Field(None, description="Фамилия")
    created_at: datetime = Field(..., description="Дата регистрации")
    is_superuser: bool = Field(..., description="Флаг суперпользователя")
    gender: str | None = Field(None, description="Пол")
    age_group: str | None = Field(None, description="Возрастная группа")
    country: str | None = Field(None, description="ISO-код страны")
    roles: list[RoleResponse] = Field(default_factory=list, description="Список ролей пользователя")

    class Config:
        from_attributes = True
