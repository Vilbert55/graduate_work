from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="NOTIFICATIONS_",
        case_sensitive=False,
        extra="ignore",
    )

    # Общие
    project_name: str = Field("Notifications Service", alias="PROJECT_NAME")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # PostgreSQL (общая БД проекта)
    postgres_user: str = Field("postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("movies", alias="POSTGRES_DB")
    postgres_host: str = Field("movies-db", alias="SQL_HOST")
    postgres_port: int = Field(5432, alias="DB_PORT")

    # RabbitMQ (с префиксом NOTIFICATIONS_)
    rabbit_host: str = "movies-rabbitmq"
    rabbit_port: int = 5672
    rabbit_user: str = "guest"
    rabbit_password: str = "guest"  # noqa: S105
    rabbit_vhost: str = "/"

    # SMTP
    smtp_host: str = "movies-mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@movies.local"
    smtp_use_tls: bool = False

    # JWT (тот же secret что в auth-service, нужен для WS gateway)
    jwt_secret_key: str = Field("", alias="AUTH_JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", alias="AUTH_JWT_ALGORITHM")

    # WebSocket gateway
    ws_server_host: str = "0.0.0.0"  # noqa: S104
    ws_server_port: int = 8005

    # Расписания воркеров
    scheduler_interval: int = 10
    publisher_interval: int = 2
    recovery_interval: int = 120
    publisher_batch_size: int = 200
    publisher_sleep_between_batches: float = 0.5

    # Обработка сообщений
    max_attempts: int = 5
    retry_ttl_ms: int = 30_000
    queued_stuck_timeout_sec: int = 300
    sending_stuck_timeout_sec: int = 600

    # Auth-клиент
    auth_concurrency: int = 10
    auth_timeout_sec: int = 5

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbit_url(self) -> str:
        return (
            f"amqp://{self.rabbit_user}:{self.rabbit_password}"
            f"@{self.rabbit_host}:{self.rabbit_port}/{self.rabbit_vhost.lstrip('/')}"
        )


settings = Settings()
