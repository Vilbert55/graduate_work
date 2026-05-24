from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field


class APIErrorInfo(BaseModel):
    code: str = Field(..., description="Уникальный код ошибки")
    message: str = Field(..., description="Человекочитаемое сообщение об ошибке")
    details: dict | None = Field(
        default=None,
        description="Дополнительные детали ошибки",
    )


class APIException(HTTPException):
    """Базовое исключение для всех API ошибок."""
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "API_ERROR"
    message: str = "An error occurred"
    headers: dict[str, str] | None = None

    def __init__(self, msg: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.error_info = APIErrorInfo(
            code=self.code,
            message=msg or self.message,  # Используем переданное сообщение или сообщение по умолчанию
            details=details,
        )
        super().__init__(
            status_code=self.status_code,
            detail=self.error_info.model_dump(),
            headers=self.headers,
        )


# -------------------------------------------------------------------
# Базовые категории ошибок
# -------------------------------------------------------------------

class BadRequestError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    message = "Bad request"


class UnauthorizedError(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "Unauthorized"
    headers = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "Forbidden"


class NotFoundError(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "Resource not found"


class ConflictError(APIException):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "Conflict"


# -------------------------------------------------------------------
# Исключения для сервиса авторизации
# -------------------------------------------------------------------

class CredentialsError(UnauthorizedError):
    """Неверные учетные данные."""
    code = "CREDENTIALS_ERROR"
    message = "Invalid authentication credentials"


class UserAlreadyExistsError(ConflictError):
    """Пользователь с таким логином уже существует."""
    code = "USER_ALREADY_EXISTS"
    message = "User with this login already exists"


class RoleNotFoundError(NotFoundError):
    """Роль не найдена."""
    code = "ROLE_NOT_FOUND"
    message = "Role not found"


class PermissionDeniedError(ForbiddenError):
    """Недостаточно прав."""
    code = "PERMISSION_DENIED"
    message = "Not enough permissions"


class UserNotFoundError(NotFoundError):
    """Пользователь не найден."""
    code = "USER_NOT_FOUND"
    message = "User not found"


class LoginAlreadyTakenError(ConflictError):
    """Логин уже занят."""
    code = "LOGIN_ALREADY_TAKEN"
    message = "Login already taken"


class InputValidationError(BadRequestError):
    """Ошибка валидации входных данных."""
    code = "VALIDATION_ERROR"
    message = "Validation error"


class RateLimitExceededError(APIException):
    """Превышен лимит запросов."""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please try again later."


class OAuthLinkRequiredError(ConflictError):
    """Пользователь с таким email уже существует, требуется привязка OAuth-аккаунта."""
    status_code = status.HTTP_409_CONFLICT
    code = "OAUTH_LINK_REQUIRED"
    message = "User with this email already exists. Please link your account."
