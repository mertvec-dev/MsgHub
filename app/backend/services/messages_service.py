"""
Сервис сообщений — отправка, получение, редактирование

Отвечает за:
  - Проверку членства в комнате
  - Шифрование контента (Fernet)
  - Сохранение в БД с обновлением активности комнаты
  - Cursor-based пагинацию (скролл в историю)
  - Проверку прав при редактировании
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from typing import Any, List, Dict, Optional
from datetime import datetime

from sqlmodel import select
from sqlalchemy import delete as sql_delete, func
from sqlalchemy.exc import IntegrityError

from database.engine import db_engine
from database.models.messages import Message
from database.models.message_reads import MessageRead
from database.models.rooms import Room
from database.models.room_member import RoomMember
from database.models.users import User

from app.backend.utils.crypto import crypto_manager


# ============================================================================
# СЕРВИС
# ============================================================================

class MessageService:
    """
    Управление сообщениями: создание, чтение (пагинация), редактирование.
    """

    # ==========================================================================
    # ОТПРАВКА СООБЩЕНИЯ
    # ==========================================================================

    async def send_message(self, sender_id: int, room_id: int, content: str) -> Message:
        """
        Создаёт новое сообщение в комнате.

        Шаги:
        1. Проверяет что отправитель состоит в комнате (JOIN RoomMember + Room).
        2. Шифрует контент через Fernet.
        3. Сохраняет сообщение в БД.
        4. Обновляет updated_at комнаты (для сортировки чатов по последнему сообщению).
        5. Коммитит всё в одной транзакции.

        Оптимизация: один запрос с JOIN вместо двух отдельных.
        """
        async for session in db_engine.get_async_session():
            # 1. Проверяем членство + получаем комнату в одном запросе
            result = await session.execute(
                select(RoomMember, Room)
                .join(Room, RoomMember.room_id == Room.id)
                .where(
                    (RoomMember.room_id == room_id) & (RoomMember.user_id == sender_id)
                )
            )
            row = result.first()

            # Если пользователь не состоит в комнате — ошибка
            if not row:
                raise ValueError("Вы не являетесь участником этой комнаты")

            member, room = row

            # 2. Шифруем контент (Fernet AES)
            encrypted_content = await crypto_manager.encrypt_message_async(content)

            # 3. Создаём сообщение
            message = Message(
                room_id=room_id,
                sender_id=sender_id,
                content=content,               # Открытый текст (в БД для чтения)
                encrypted_content=encrypted_content,  # Зашифрованная копия
            )
            session.add(message)

            # 4. Обновляем время активности комнаты (фронт сортирует чаты по этому полю)
            room.updated_at = datetime.utcnow()
            session.add(room)

            # 5. Коммит — всё или ничего
            await session.commit()
            await session.refresh(message)
            return message

    # ==========================================================================
    # ПОЛУЧЕНИЕ СООБЩЕНИЙ (CURSOR-ПАГИНАЦИЯ)
    # ==========================================================================

    async def get_messages(
        self,
        room_id: int,
        user_id: int,
        limit: int = 50,
        cursor: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Загружает сообщения из комнаты с пагинацией.

        **Как работает cursor:**
        - cursor=None → последние 50 сообщений (самые новые).
        - cursor=123 → 50 сообщений СТАРШЕ сообщения с ID=123 (скролл вверх).

        **Почему cursor, а не offset?**
        Offset медленный на больших таблицах (пропускает N строк).
        Cursor использует индекс по ID — O(log N) вместо O(N).

        **Возвращаемый формат:**
        - messages: список сообщений (от старых к новым — для UI).
        - next_cursor: ID самого старого сообщения в пачке (для следующего запроса).
        - has_more: есть ли ещё сообщения.
        """
        async for session in db_engine.get_async_session():
            # 1. Проверяем что пользователь состоит в комнате
            result = await session.execute(
                select(RoomMember).where(
                    (RoomMember.room_id == room_id) & (RoomMember.user_id == user_id)
                )
            )
            member = result.scalars().first()
            if not member:
                raise ValueError("Вы не являетесь участником этой комнаты")

            # 2. Формируем запрос: сообщения + никнейм отправителя
            query = (
                select(Message, User.nickname.label("sender_nickname"))
                .join(User, Message.sender_id == User.id)
                .where(Message.room_id == room_id)
            )

            # 3. Cursor: грузим сообщения с ID < cursor (более старые)
            if cursor:
                query = query.where(Message.id < cursor)

            # 4. Сортировка: сначала новые (по убыванию ID)
            query = query.order_by(Message.id.desc()).limit(limit)

            result = await session.execute(query)
            rows = result.all()

            # 5. Разворачиваем массив — в UI сообщения идут от старых к новым
            messages: List[Dict[str, Any]] = []
            for msg, nickname in reversed(rows):
                # Свои сообщения: ✓✓ если кто-то из других участников прочитал (есть message_reads не от отправителя).
                # Чужие: отметка «я прочитал» — для бейджей на фронте не используется.
                if msg.sender_id == user_id:
                    is_read_res = await session.execute(
                        select(MessageRead.id).where(
                            MessageRead.message_id == msg.id,
                            MessageRead.user_id != msg.sender_id,
                        ).limit(1)
                    )
                else:
                    is_read_res = await session.execute(
                        select(MessageRead.id).where(
                            MessageRead.message_id == msg.id,
                            MessageRead.user_id == user_id,
                        ).limit(1)
                    )
                is_read = is_read_res.scalars().first() is not None

                messages.append({
                    "id": msg.id,
                    "room_id": msg.room_id,
                    "sender_id": msg.sender_id,
                    "sender_nickname": nickname,
                    "content": msg.content,
                    "is_edited": msg.is_edited,
                    "is_read": is_read,
                    "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                })

            # 6. Общее количество сообщений в комнате (для UI — "всего 1234 сообщений")
            count_res = await session.execute(
                select(func.count(Message.id)).where(Message.room_id == room_id)
            )
            total_count = count_res.scalar()

            # 7. Next cursor = ID самого старого сообщения (первого в развёрнутом списке)
            next_cursor = messages[0]["id"] if messages else None

            return {
                "messages": messages,
                "total": total_count,
                "limit": limit,
                "next_cursor": next_cursor,
                "has_more": len(messages) == limit,
            }

    # ==========================================================================
    # ПРЕВЬЮ ПОСЛЕДНЕГО СООБЩЕНИЯ
    # ==========================================================================

    async def get_last_message_preview(self, room_id: int) -> Optional[Dict[str, Any]]:
        """
        Возвращает последнее сообщение комнаты.
        Нужно для отображения превью в списке чатов ("Последнее: ...").
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Message, User.nickname.label("sender_nickname"))
                .join(User, Message.sender_id == User.id)
                .where(Message.room_id == room_id)
                .order_by(Message.id.desc())
                .limit(1)
            )
            row = result.first()
            if not row:
                return None

            msg, nickname = row
            return {
                "sender_nickname": nickname,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }

    # ==========================================================================
    # РЕДАКТИРОВАНИЕ
    # ==========================================================================

    async def edit_message(self, message_id: int, user_id: int, new_content: str) -> Message:
        """
        Редактирует текст сообщения.

        Шаги:
        1. Находит сообщение по ID.
        2. Проверяет что текущий пользователь — автор.
        3. Шифрует новый контент.
        4. Обновляет поля: content, encrypted_content, is_edited, edited_at.
        5. Коммит.
        """
        async for session in db_engine.get_async_session():
            # 1. Находим сообщение
            result = await session.execute(select(Message).where(Message.id == message_id))
            message = result.scalars().first()
            if not message:
                raise ValueError("Сообщение не найдено")

            # 2. Проверка прав — только автор может редактировать
            if int(message.sender_id) != int(user_id):
                raise ValueError("Вы не можете редактировать это сообщение")

            # 3. Шифруем новый контент
            encrypted_content = await crypto_manager.encrypt_message_async(new_content)

            # 4. Обновляем поля
            message.content = new_content
            message.encrypted_content = encrypted_content
            message.is_edited = True
            message.edited_at = datetime.utcnow()
            session.add(message)

            # 5. Коммит
            await session.commit()
            await session.refresh(message)
            return message

    # ==========================================================================
    # УДАЛЕНИЕ
    # ==========================================================================

    async def delete_message(self, message_id: int, user_id: int) -> int:
        """
        Удаляет сообщение (только автор).
        Возвращает room_id для уведомлений.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(select(Message).where(Message.id == message_id))
            message = result.scalars().first()
            
            if not message:
                raise ValueError("Сообщение не найдено")

            if int(message.sender_id) != int(user_id):
                raise ValueError("Вы не можете удалить это сообщение")

            room_id = message.room_id
            try:
                await session.execute(
                    sql_delete(MessageRead).where(MessageRead.message_id == message_id)
                )
                await session.flush()
                await session.execute(sql_delete(Message).where(Message.id == message_id))
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise ValueError("Не удалось удалить сообщение (ограничения БД)") from None
            return room_id


# Глобальный экземпляр — используется в роутерах
messages_service = MessageService()
