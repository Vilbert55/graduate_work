from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    login: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Уникальное имя пользователя (логин)",
        example="john_doe",
    )
    password: str = Field(
        ...,
        min_length=6,
        description="Пароль (минимум 6 символов)",
        example="StrongP@ss1",
    )
    first_name: str | None = Field(
        None,
        description="Имя",
        example="John",
    )
    last_name: str | None = Field(
        None,
        description="Фамилия",
        example="Doe",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "login": "john_doe",
                "password": "StrongP@ss1",
                "first_name": "John",
                "last_name": "Doe",
            },
        }


class UserLogin(BaseModel):
    login: str = Field(..., description="Имя пользователя (логин)")
    password: str = Field(..., description="Пароль")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token (короткоживущий)")
    refresh_token: str = Field(..., description="JWT refresh token (долгоживущий)")
    token_type: str = Field("bearer", description="Тип токена")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIs...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
                "token_type": "bearer",
            },
        }


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Действительный refresh-токен")


class PasswordChange(BaseModel):
    old_password: str = Field(..., description="Текущий пароль")
    new_password: str = Field(..., min_length=6, description="Новый пароль (минимум 6 символов)")


class LoginHistoryResponse(BaseModel):
    id: UUID = Field(..., description="Уникальный идентификатор записи")
    user_agent: str = Field(..., description="User-Agent устройства")
    ip_address: str = Field(..., description="IP-адрес, с которого выполнен вход")
    created_at: datetime = Field(..., description="Дата и время входа")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
                "ip_address": "192.168.1.100",
                "created_at": "2025-03-07T12:00:00",
            },
        }


class LoginChange(BaseModel):
    new_login: str = Field(..., min_length=3, max_length=255, description="Новый уникальный логин")
    password: str = Field(..., description="Текущий пароль для подтверждения")
