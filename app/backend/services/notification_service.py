"""
Сервис уведомлений — прочтение сообщений, счётчики непрочитанных

Управляет таблицей message_reads:
  - message_id — какое сообщение
  - user_id    — кто прочитал
  - read_at    — когда прочитал

Оптимизация: использует сырой SQL для массовых операций (тысячи сообщений за раз).
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from datetime import datetime
from typing import Dict, List

from sqlmodel import select, text

from database.engine import db_engine
from database.models.messages import Message
from database.models.message_reads import MessageRead
from database.models.room_member import RoomMember


# ============================================================================
# СЕРВИС
# ============================================================================

class NotificationService:
    """
    Управление статусами прочтения сообщений.
    """

    # ==========================================================================
    # ПОМЕТКА КАК ПРОЧИТАННОЕ
    # ==========================================================================

    async def mark_room_as_read(self, room_id: int, user_id: int) -> bool:
        """
        Помечает ВСЕ сообщения в комнате как прочитанные для пользователя.

        **Логика SQL:**
        ```
            INSERT INTO message_reads (message_id, user_id, read_at)
            SELECT m.id, :user_id, :now
            FROM messages m
            WHERE m.room_id = :room_id
            AND NOT EXISTS (              -- Только те, что ещё не прочитаны
                SELECT 1 FROM message_reads mr
                WHERE mr.message_id = m.id AND mr.user_id = :user_id
            )
        ```
        """
        async for session in db_engine.get_async_session():
            await session.execute(
                text("""
                    INSERT INTO message_reads (message_id, user_id, read_at)
                    SELECT m.id, :user_id, :now
                    FROM messages m
                    WHERE m.room_id = :room_id
                    AND NOT EXISTS (
                        SELECT 1 FROM message_reads mr
                        WHERE mr.message_id = m.id AND mr.user_id = :user_id
                    )
                """),
                {"room_id": room_id, "user_id": user_id, "now": datetime.utcnow()},
            )
            await session.commit()
            return True

    # ==========================================================================
    # СЧЁТЧИК НЕПРОЧИТАННЫХ
    # ==========================================================================

    async def get_unread_count(self, user_id: int) -> Dict[int, int]:
        """
        Возвращает количество непрочитанных сообщений по каждой комнате.

        **Логика SQL:**
        Берём все сообщения в комнатах пользователя.
        LEFT JOIN с message_reads — если прочитано, будет запись.
        Считаем где mr.id IS NULL — значит НЕ прочитано.

        **Возвращает:**
        {room_id: count, ...} — например {1: 5, 3: 12}
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                text("""
                    SELECT m.room_id, COUNT(m.id) as unread
                    FROM messages m
                    JOIN room_members rm ON rm.room_id = m.room_id
                    LEFT JOIN message_reads mr
                        ON mr.message_id = m.id AND mr.user_id = :user_id
                    WHERE rm.user_id = :user_id
                    AND mr.id IS NULL
                    GROUP BY m.room_id
                """),
                {"user_id": user_id},
            )
            rows = result.all()
            return {row.room_id: row.unread for row in rows}

    # ==========================================================================
    # НЕПРОЧИТАННЫЕ СООБЩЕНИЯ
    # ==========================================================================

    async def get_unread_messages(self, room_id: int, user_id: int) -> List[Message]:
        """
        Возвращает список непрочитанных сообщений в конкретной комнате.
        OUTER JOIN: сообщение есть, а записи о прочтении нет.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Message)
                .outerjoin(
                    MessageRead,
                    (MessageRead.message_id == Message.id) & (MessageRead.user_id == user_id),
                )
                .where(
                    (Message.room_id == room_id) & (MessageRead.id == None)
                )
                .order_by(Message.created_at.asc())
            )
            return result.scalars().all()

    # ==========================================================================
    # ПРОВЕРКА ПРОЧТЕНИЯ
    # ==========================================================================

    async def is_message_read(self, message_id: int, user_id: int) -> bool:
        """Проверяет, прочитано ли конкретное сообщение пользователем."""
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(MessageRead).where(
                    (MessageRead.message_id == message_id) &
                    (MessageRead.user_id == user_id)
                )
            )
            return result.scalars().first() is not None


# Глобальный экземпляр
notification_service = NotificationService()
