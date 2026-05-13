"""Централизованная настройка логирования."""

import logging
import sys


def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(stream=sys.stdout, level=level, format=fmt, force=True)
    # Глушим шумные сторонние логгеры
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
