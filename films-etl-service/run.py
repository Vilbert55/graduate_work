from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from config import config
from extract import PostgresExtractor
from load import ElasticsearchLoader
from logger import logger
from pipeline import ETLProcess
from state_handler import JsonFileStorage, State


def run_etl_movies() -> None:
    """Запуск ETL-процесса."""
    storage = JsonFileStorage(config.etl.state_file_path)
    state = State(storage)

    extractor = PostgresExtractor()
    loader = ElasticsearchLoader()

    etl_process = ETLProcess(
        extractor=extractor,
        loader=loader,
        state=state,
    )

    logger.info("ETL movies process running...")
    etl_process.run()


def main() -> None:
    """Основная функция запуска планировщика."""
    scheduler = BlockingScheduler()

    scheduler.add_job(
        run_etl_movies,
        CronTrigger.from_crontab(config.etl.cron_schedule),
        id="etl_job",
        name="ETL process",
        replace_existing=True,
    )

    logger.info("Scheduler starting")
    scheduler.start()


if __name__ == "__main__":
    main()
