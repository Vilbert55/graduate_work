from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Postgres (общая БД проекта) — имена env-переменных как у остальных сервисов.
    postgres_user: str = Field("postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("movies", alias="POSTGRES_DB")
    postgres_host: str = Field("movies-db", alias="SQL_HOST")
    postgres_port: int = Field(5432, alias="DB_PORT")

    # Kafka (для trigger-events) — внутри сети compose адрес фиксирован.
    kafka_bootstrap: str = "movies-kafka:9092"
    kafka_topic_views: str = "views"

    @property
    def database_dsn(self) -> str:
        return (
            f"postgres://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
