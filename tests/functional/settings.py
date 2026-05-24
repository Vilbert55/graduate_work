import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


def get_es_schema_path() -> Path:
    """Определяет путь к файлу es_schema_movies.json в зависимости от окружения."""
    container_path = Path("/opt/project/es_schema_movies.json")
    if container_path.exists():
        return container_path
    host_path = Path(__file__).parent.parent.parent / "es_schema_movies.json"
    if host_path.exists():
        return host_path
    raise FileNotFoundError(
        "es_schema_movies.json не найден. Убедитесь, что файл существует "
        "в корне проекта и правильно смонтирован в контейнер.",
    )


def load_es_schema() -> dict:
    """Загружает полную схему индекса (settings + mappings) из JSON-файла."""
    path = get_es_schema_path()
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class TestSettings(BaseSettings):
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    # Elasticsearch
    es_host: str = Field("movies-elasticsearch-test", alias="ELASTICSEARCH_HOST")
    es_port: int = Field(9200, alias="ELASTICSEARCH_PORT")
    es_index: str = Field("movies", alias="ELASTICSEARCH_INDEX")
    es_id_field: str = Field("id")
    es_schema: dict = Field(default_factory=load_es_schema)

    # Redis
    redis_host: str = Field("movies-redis-test", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")

    # FastAPI
    service_url: str = Field("http://movies-films-search-service-test:8001", alias="FASTAPI_URL")

    @property
    def elastic_url(self) -> str:
        """Полный URL для подключения к Elasticsearch."""
        return f"http://{self.es_host}:{self.es_port}"


test_settings = TestSettings()
