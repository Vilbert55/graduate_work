from datetime import UTC, datetime

from extract import PostgresExtractor
from load import ElasticsearchLoader
from logger import logger
from state_handler import State
from transform import transform_film_data


class ETLProcess:
    """Основной класс ETL-процесса."""

    def __init__(
        self,
        extractor: PostgresExtractor,
        loader: ElasticsearchLoader,
        state: State,
    ) -> None:
        self.extractor = extractor
        self.loader = loader
        self.state = state

    def _initialize_state(self) -> tuple[datetime, datetime, int]:
        """Инициализировать состояние ETL процесса."""
        state_data = self.state.get_state()

        extract_dttm_current = state_data.extract_dttm_current or datetime.now(UTC)
        extract_dttm_last = state_data.extract_dttm_last or datetime.fromisoformat("1970-01-01T00:00:00")
        offset = state_data.offset

        # Сохраняем текущее время если оно не было установлено
        if state_data.extract_dttm_current is None:
            self.state.set_state(extract_dttm_current=extract_dttm_current, offset=0)

        return extract_dttm_current, extract_dttm_last, offset

    def _finalize_state(self, extract_dttm_current: datetime) -> None:
        """Завершить состояние ETL процесса."""
        self.state.set_state(
            extract_dttm_last=extract_dttm_current,
            extract_dttm_current=None,
            offset=0,
        )

    def run(self) -> None:
        """Запуск ETL-процесса."""
        extract_dttm_current, extract_dttm_last, offset = self._initialize_state()

        logger.info(
            f"Starting ETL process. Current time: {extract_dttm_current}, "
            f"Last successful load: {extract_dttm_last}, Offset: {offset}",
        )

        while True:
            changes, has_more = self.extractor.extract_changed_film_ids(
                extract_dttm_current=extract_dttm_current,
                extract_dttm_last=extract_dttm_last,
                offset=offset,
            )

            if not changes:
                break

            film_ids = [str(change.id) for change in changes]
            film_data = self.extractor.extract_film_data(film_ids)

            if film_data:
                transformed_data = transform_film_data(film_data)
                self.loader.load(transformed_data)

            offset += len(changes)
            self.state.set_state(offset=offset)
            logger.info(f"Processed {len(changes)} films. New offset: {offset}")

            if not has_more:
                break

        self._finalize_state(extract_dttm_current)
        logger.info("ETL process completed successfully")
