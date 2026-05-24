import logging
import sys

from src.core.config import settings


def setup_logging(component: str) -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    return logging.getLogger(component)
