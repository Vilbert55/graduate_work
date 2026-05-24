
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения."""

    model_config = {
        'env_file': '.env',
        'env_file_encoding': 'utf-8',
        'case_sensitive': False,
        "extra": "ignore",
    }

    # Это в Swagger-документации используется
    project_name: str = Field('movies', alias='PROJECT_NAME')

    # Redis
    redis_host: str = Field('127.0.0.1', alias='REDIS_HOST')
    redis_port: int = Field(6379, alias='REDIS_PORT')

    # Elasticsearch
    elastic_host: str = Field('127.0.0.1', alias='ELASTICSEARCH_HOST')
    elastic_port: int = Field(9200, alias='ELASTICSEARCH_PORT')
    elastic_schema: str = Field('http://', alias='ELASTICSEARCH_SCHEMA')

    # логирование
    log_level: str = Field('INFO', alias='LOG_LEVEL')

    # Настройки сервера
    host: str = '0.0.0.0'  # noqa: S104
    port: int = 8001
    reload: bool = False

    @property
    def elastic_url(self) -> str:
        """URL для подключения к Elasticsearch."""
        return f"{self.elastic_schema}{self.elastic_host}:{self.elastic_port}"

    @property
    def redis_url(self) -> str:
        """URL для подключения к Redis."""
        return f"redis://{self.redis_host}:{self.redis_port}"

    # JWT settings (берём из переменных AUTH_*)
    jwt_secret_key: str = Field(..., alias='AUTH_JWT_SECRET_KEY')
    jwt_algorithm: str = Field('HS256', alias='AUTH_JWT_ALGORITHM')

    # для http-запросов к auth-service
    auth_host: str = Field('movies-auth-service', alias='AUTH_SERVER_HOST')
    auth_port: int = Field(8002, alias='AUTH_SERVER_PORT')

    # Sentry (пустая строка отключает интеграцию)
    sentry_dsn: str = Field('', alias='FILMS_SEARCH_SENTRY_DSN')


settings = Settings()
