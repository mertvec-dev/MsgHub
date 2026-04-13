"""Настройка логирования backend-приложения."""

import logging

from app.backend.config import settings


def configure_logging() -> None:
    """Применяет единый формат и уровень логов для backend."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

