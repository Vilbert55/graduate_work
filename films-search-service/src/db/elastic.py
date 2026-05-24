from elasticsearch import AsyncElasticsearch

from src.core.config import settings


async def get_elastic_client() -> AsyncElasticsearch:  # noqa: RUF029
    """Создать и вернуть клиент Elasticsearch."""
    return AsyncElasticsearch(
        hosts=[settings.elastic_url],
    )
