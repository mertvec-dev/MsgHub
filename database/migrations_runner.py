"""Запуск Alembic из кода (без отдельного процесса)."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def run_alembic_upgrade_head() -> None:
    """Применяет миграции до head. Работает из отдельного потока (см. lifespan)."""
    root = Path(__file__).resolve().parent.parent
    ini = root / "alembic.ini"
    if not ini.is_file():
        logger.warning("Файл %s не найден — пропускаем Alembic", ini)
        return
    cfg = Config(str(ini))
    command.upgrade(cfg, "head")
    logger.info("Миграции Alembic применены (head)")
