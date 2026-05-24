from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения community-content-service."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='COMMUNITY_',  # специфичные для сервиса переменные с префиксом
        case_sensitive=False,
        extra='ignore',
    )

    # ----- Общие переменные (без префикса) -----
    project_name: str = Field('Community Content Service', alias='PROJECT_NAME')

    # PostgreSQL
    postgres_user: str = Field('postgres', alias='POSTGRES_USER')
    postgres_password: str = Field(alias='POSTGRES_PASSWORD')
    postgres_db: str = Field('movies', alias='POSTGRES_DB')
    postgres_host: str = Field('localhost', alias='SQL_HOST')
    postgres_port: int = Field(5438, alias='DB_PORT')

    # Логирование
    log_level: str = Field('INFO', alias='LOG_LEVEL')

    # JWT (общие настройки авторизации, берутся из переменных AUTH_*)
    jwt_secret_key: str = Field(..., alias='AUTH_JWT_SECRET_KEY')
    jwt_algorithm: str = Field('HS256', alias='AUTH_JWT_ALGORITHM')

    # ----- Специфичные для сервиса (с префиксом COMMUNITY_) -----
    # Сервер
    server_host: str = '0.0.0.0'  # noqa: S104
    server_port: int = 8004
    server_reload: bool = False

    # Debug
    debug: bool = False

    # Jaeger
    jaeger_endpoint: str = 'movies-jaeger:4317'

    # Sentry (пустая строка отключает интеграцию)
    sentry_dsn: str = ''

    @property
    def database_url(self) -> str:
        """Строка подключения к БД через asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
