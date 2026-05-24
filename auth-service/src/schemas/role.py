from uuid import UUID

from pydantic import BaseModel, Field


class RoleCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Уникальное название роли, например 'admin' или 'movie_viewer'",
        example="content_manager",
    )
    description: str | None = Field(
        None,
        max_length=255,
        description="Описание роли (необязательно)",
        example="Управляет контентом",
    )


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50, description="Новое название роли (если меняется)")
    description: str | None = Field(None, max_length=255, description="Новое описание роли (если меняется)")


class RoleResponse(BaseModel):
    id: UUID = Field(..., description="Уникальный идентификатор роли")
    name: str = Field(..., description="Название роли")
    description: str | None = Field(None, description="Описание роли")

    class Config:
        from_attributes = True


class UserRoleAssign(BaseModel):
    user_id: str
    role_id: str
