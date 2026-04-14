"""Lifespan приложения: startup/shutdown задачи."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.backend.services import pubsub
from database.engine import db_engine
from database.migrations_runner import run_alembic_upgrade_head

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """
    Инициализирует инфраструктуру приложения.

    На старте:
    - готовит БД;
    - запускает слушатель Redis pub/sub.

    При остановке:
    - закрывает пул БД.
    """
    logger.info("Запуск MsgHub Backend...")
    # Сначала create_all: на пустой БД создаются таблицы из моделей. Миграции Alembic
    # делают ALTER … IF NOT EXISTS — они предполагают, что таблицы уже есть.
    await db_engine.init_db()
    # Alembic вызывает asyncio.run() внутри env.py — в отдельном потоке.
    await asyncio.to_thread(run_alembic_upgrade_head)
    logger.info("База данных готова")

    try:
        asyncio.create_task(pubsub.start_pubsub_listener())
        logger.info("Pub/Sub слушатель запущен")
    except Exception as exc:  # pragma: no cover - логируем защитно
        logger.error("Ошибка запуска Pub/Sub: %s", exc)

    yield

    logger.info("Остановка сервера...")
    await db_engine.close_db()
    logger.info("БД отключена")

