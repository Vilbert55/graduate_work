from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ALERTING_",
        case_sensitive=False,
        extra="ignore",
    )

    # Общие
    log_level: str = Field("INFO", alias="ALERTING_LOG_LEVEL")

    # Postgres (общая БД проекта; схема alerting)
    postgres_user: str = Field("postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("movies", alias="POSTGRES_DB")
    postgres_host: str = Field("movies-db", alias="SQL_HOST")
    postgres_port: int = Field(5432, alias="DB_PORT")

    # StarRocks (alert_reader, только SELECT на ugc_analytics)
    starrocks_host: str = "movies-starrocks"
    starrocks_port: int = 9030
    starrocks_user: str = "alert_reader"
    starrocks_password: str = "alert_reader"  # noqa: S105 — дефолтный dev-пароль
    starrocks_db: str = "ugc_analytics"

    # Sentry — пусто отключает интеграцию
    sentry_dsn: str = ""

    # Параметры движка
    rules_refresh_interval_sec: int = 60     # как часто перечитывать t_rules
    starrocks_query_timeout_sec: int = 30    # тайм-аут SQL-правила
    starrocks_connect_timeout_sec: int = 10  # тайм-аут установки соединения со StarRocks
    dispatch_retention_days: int = 90        # хранение t_dispatch_history (retention партиций)
    recovery_grace_sec: int = 300            # старше скольки секунд «running» запуск считаем осиротевшим
    # Общий потолок писем на пользователя в сутки по ВСЕМ правилам (0 — выключен).
    # Один на всю систему: страхует от перекрытия правил (см. frequency cap).
    global_per_user_per_day: int = 3

    @property
    def _pg_dsn_tail(self) -> str:
        # Общая часть DSN: creds@host:port/db (схему дописывает каждый потребитель).
        return (
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url(self) -> str:
        # Для SQLAlchemy: схема обязана указывать драйвер (+asyncpg).
        return f"postgresql+asyncpg://{self._pg_dsn_tail}"

    @property
    def asyncpg_dsn(self) -> str:
        # Для прямого asyncpg.connect() (LISTEN/NOTIFY): обычный libpq-DSN без драйвера.
        return f"postgresql://{self._pg_dsn_tail}"


settings = Settings()
