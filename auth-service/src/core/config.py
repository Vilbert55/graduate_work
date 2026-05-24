from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_prefix='AUTH_',          # Префикс для полей без alias
        case_sensitive=False,
        extra='ignore',
    )

    # ----- Общие переменные (без префикса AUTH_) -----
    project_name: str = Field('Auth Service', alias='PROJECT_NAME')

    # PostgreSQL
    postgres_user: str = Field('postgres', alias='POSTGRES_USER')
    postgres_password: str = Field(alias='POSTGRES_PASSWORD')
    postgres_db: str = Field('movies', alias='POSTGRES_DB')
    postgres_host: str = Field('localhost', alias='SQL_HOST')
    postgres_port: int = Field(5438, alias='DB_PORT')

    # Redis
    redis_host: str = Field('127.0.0.1', alias='REDIS_HOST')
    redis_port: int = Field(6379, alias='REDIS_PORT')
    redis_db: int = 1

    # Логирование
    log_level: str = Field('INFO', alias='LOG_LEVEL')

    # ----- Специфичные для сервиса авторизации (с префиксом AUTH_) -----
    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Суперпользователь
    superuser_login: str | None = None
    superuser_password: str | None = None

    # Сервер
    server_host: str = '0.0.0.0'  # noqa: S104
    server_port: int = 8002
    server_reload: bool = False

    # Debug
    debug: bool = False

    # Sentry (пустая строка отключает интеграцию)
    sentry_dsn: str = ''

    # Rate limits
    login_rate_limit_requests: int
    login_rate_limit_period: int
    register_rate_limit_requests: int
    register_rate_limit_period: int

    # OAuth
    yandex_client_id: str
    yandex_client_secret: str

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}"


settings = Settings()
