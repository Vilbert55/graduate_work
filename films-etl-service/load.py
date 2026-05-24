from typing import Any

import backoff
from config import config
from elasticsearch import Elasticsearch, helpers
from logger import logger


class ElasticsearchLoader:
    """Загрузка данных в Elasticsearch."""

    def __init__(self, index_name: str = "movies"):
        self.host = f"http://{config.elasticsearch.host}:{config.elasticsearch.port}"
        self.index_name = index_name
        self._client: Elasticsearch | None = None

    @property
    def client(self) -> Elasticsearch:
        """Клиент Elasticsearch с ленивой инициализацией."""
        if self._client is None or not self._client.ping():
            self._client = Elasticsearch(hosts=self.host)
        return self._client

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=10,
        logger=logger,
    )
    def load(self, data: list[dict[str, Any]]) -> None:
        """Загрузить данные в Elasticsearch."""
        if not data:
            return

        actions = [
            {
                "_index": self.index_name,
                "_id": doc["id"],
                "_source": doc,
            }
            for doc in data
        ]

        if not self.client.ping():
            logger.error("Connection to Elasticsearch failed")
            raise ConnectionError("Elasticsearch is unavailable")

        try:
            _success, failed = helpers.bulk(
                self.client,
                actions,
                stats_only=False,
                raise_on_error=True,
                request_timeout=10,
            )

            if failed:
                for error in failed:
                    logger.error(f"Failed to load document: {error}")
                raise RuntimeError(f"Failed to load {len(failed)} documents")

            logger.info(f"Successfully loaded {len(data)} documents")

        except helpers.BulkIndexError as e:
            logger.error(f"Bulk loading error: {e}")
            for error in e.errors:
                logger.error(f"Error details: {error}")
            raise
