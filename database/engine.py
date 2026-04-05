"""
Движок базы данных — подключение, сессии, инициализация

Использует:
  - SQLAlchemy Async Engine — асинхронное подключение к PostgreSQL.
  - SQLModel — ORM + Pydantic-валидация в одном.
  - Connection Pool — переиспользует подключения (экономит ресурсы).
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import logging

from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.backend.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# ДВИЖОК БД
# ============================================================================

class DB_Engine:
    """
    Обёртка над SQLAlchemy Engine

    **Connection Pool настройки:**
    - pool_size=10: максимум 10 подключений держатся открытыми
    - max_overflow=20: можно создать ещё 20 при пиковой нагрузке
    - pool_timeout=30: ждать свободное подключение не более 30 сек
    - pool_recycle=3600: пересоздавать подключение через 1 час (защита от stale)
    """

    def __init__(self):
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,  # True — логировать SQL-запросы (для отладки)
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=3600,
        )

    async def init_db(self):
        """
        Создаёт все таблицы из SQLModel-моделей

        Если таблицы уже существуют — пропускает
        Если таблицы нет — создаёт (включая индексы, foreign keys)
        """
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
                logger.info("БД ГОТОВА")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
            raise

    async def get_async_session(self):
        """
        Генератор асинхронной сессии — используется в сервисах

        Пример:
        ```
            async for session in db_engine.get_async_session():
                result = await session.execute(select(User))
        ```

        Сессия автоматически закрывается после выхода из блока
        """
        async with AsyncSession(self.engine) as session:
            yield session

    async def close_db(self):
        """
        Закрывает все подключения в пуле.
        Вызывается при shutdown сервера.
        """
        await self.engine.dispose()
        logger.info("Подключения к БД закрыты")


# Глобальный экземпляр — используется в сервисах и роутерах
db_engine = DB_Engine()
