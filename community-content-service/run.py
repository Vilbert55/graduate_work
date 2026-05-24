import logging.config

import uvicorn

from src.core.config import settings
from src.core.logger import LOGGING_CONFIG
from src.main import app


logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


def main() -> None:
    """Запуск приложения."""
    log_level = settings.log_level.lower()
    logger.info("Running the application on %s:%s", settings.server_host, settings.server_port)
    logger.info("Logging level: %s", log_level)

    uvicorn.run(
        app,
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.server_reload,
        log_level=log_level,
        log_config=LOGGING_CONFIG,
        access_log=True,
    )


if __name__ == "__main__":
    main()
