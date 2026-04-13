"""
Сервис сообщений — отправка, получение, редактирование

Отвечает за:
  - Проверку членства в комнате
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
from database.models.devices import Device
from database.models.friendships import Friendship, FriendshipStatus
from database.models.rooms import Room
from database.models.room_member import RoomMember, MembershipStatus
from database.models.room_key_envelopes import RoomKeyEnvelope
from database.models.users import User


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

    async def send_message(
        self,
        sender_id: int,
        room_id: int,
        content: str,
        nonce: str,
        key_version: Optional[int] = None,
        sender_device_id: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Message:
        """
        Создаёт новое сообщение в комнате.

        Шаги:
        1. Проверяет что отправитель состоит в комнате (JOIN RoomMember + Room).
        2. Проверяет E2E-данные (ciphertext + nonce + key_version).
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
                    (RoomMember.room_id == room_id)
                    & (RoomMember.user_id == sender_id)
                    & (RoomMember.status != MembershipStatus.BANNED)
                )
            )
            row = result.first()

            # Если пользователь не состоит в комнате — ошибка
            if not row:
                raise ValueError("Вы не являетесь участником этой комнаты")

            _member, room = row
            if (
                room.type == "group"
                and getattr(_member, "muted_until", None) is not None
                and _member.muted_until > datetime.utcnow()
            ):
                raise ValueError("Вы временно не можете писать в эту группу (muted)")
            if room.type == "direct":
                await self._ensure_direct_not_blocked(session, room.id, sender_id)
            await self._ensure_e2e_ready_for_send(
                session=session,
                room=room,
                sender_id=sender_id,
                sender_device_id=sender_device_id,
                key_version=key_version,
            )
            if reply_to_message_id is not None:
                reply_res = await session.execute(
                    select(Message.id).where(
                        Message.id == int(reply_to_message_id),
                        Message.room_id == room_id,
                    )
                )
                if not reply_res.scalar():
                    raise ValueError("Сообщение для ответа не найдено в этой комнате")

            # 3. Создаём сообщение
            message = Message(
                room_id=room_id,
                sender_id=sender_id,
                sender_device_id=sender_device_id,
                content=content,  # ciphertext
                nonce=nonce,
                key_version=key_version or getattr(room, "current_key_version", 1) or 1,
                reply_to_message_id=reply_to_message_id,
            )
            session.add(message)

            # 4. Обновляем время активности комнаты (фронт сортирует чаты по этому полю)
            room.updated_at = datetime.utcnow()
            session.add(room)

            # 5. Коммит — всё или ничего
            await session.commit()
            await session.refresh(message)
            return message

    async def _ensure_e2e_ready_for_send(
        self,
        session,
        room: Room,
        sender_id: int,
        sender_device_id: Optional[str],
        key_version: Optional[int],
    ) -> None:
        """
        Серверная проверка готовности E2E перед отправкой.
        Фронту не доверяем: если ключи/конверты не готовы, блокируем отправку.
        """
        if room.type == "direct":
            if not sender_device_id:
                raise ValueError("E2E не готово: отсутствует sender_device_id")

            sender_device_res = await session.execute(
                select(Device).where(
                    Device.user_id == sender_id,
                    Device.device_id == sender_device_id,
                    Device.public_key.is_not(None),
                )
            )
            if not sender_device_res.scalars().first():
                raise ValueError("E2E не готово: ключ устройства отправителя не зарегистрирован")

            members_res = await session.execute(
                select(RoomMember.user_id).where(
                    RoomMember.room_id == room.id,
                    RoomMember.user_id != sender_id,
                    RoomMember.status != MembershipStatus.BANNED,
                )
            )
            peer_ids = [int(uid) for uid in members_res.scalars().all()]
            if not peer_ids:
                raise ValueError("E2E не готово: собеседник не найден")

            for peer_id in peer_ids:
                peer_key_res = await session.execute(
                    select(Device.id).where(
                        Device.user_id == peer_id,
                        Device.public_key.is_not(None),
                    ).limit(1)
                )
                if not peer_key_res.scalars().first():
                    raise ValueError("E2E не готово: у собеседника нет зарегистрированного ключа устройства")

        elif room.type == "group":
            expected_version = int(getattr(room, "current_key_version", 1) or 1)
            if key_version is not None and int(key_version) != expected_version:
                raise ValueError("E2E не готово: неверная версия ключа комнаты")

            envelope_res = await session.execute(
                select(RoomKeyEnvelope.id).where(
                    RoomKeyEnvelope.room_id == room.id,
                    RoomKeyEnvelope.user_id == sender_id,
                    RoomKeyEnvelope.key_version == expected_version,
                ).limit(1)
            )
            if not envelope_res.scalars().first():
                raise ValueError("E2E не готово: отсутствует конверт ключа комнаты для отправителя")

    async def _ensure_direct_not_blocked(self, session, room_id: int, sender_id: int) -> None:
        """
        Проверяет, что direct-диалог не находится в состоянии BLOCKED.

        Блокировка — серверная истина: если связь заблокирована, чат недоступен для отправки/чтения.
        """
        members_res = await session.execute(
            select(RoomMember.user_id).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id != sender_id,
                RoomMember.status != MembershipStatus.BANNED,
            )
        )
        peer_ids = [int(uid) for uid in members_res.scalars().all()]
        if not peer_ids:
            return
        peer_id = peer_ids[0]
        blocked_res = await session.execute(
            select(Friendship.id).where(
                Friendship.status == FriendshipStatus.BLOCKED,
                (
                    ((Friendship.sender_id == sender_id) & (Friendship.receiver_id == peer_id))
                    | ((Friendship.sender_id == peer_id) & (Friendship.receiver_id == sender_id))
                ),
            ).limit(1)
        )
        if blocked_res.scalars().first():
            raise ValueError("Чат недоступен: один из пользователей заблокировал другого")

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
        - Offset медленный на больших таблицах (пропускает N строк).
        - Cursor использует индекс по ID — O(log N) вместо O(N).

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

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if room and room.type == "direct":
                await self._ensure_direct_not_blocked(session, room_id, user_id)

            # 2. Формируем запрос: сообщения + никнейм отправителя
            query = (
                select(
                    Message,
                    User.nickname.label("sender_nickname"),
                    User.is_admin.label("sender_is_admin"),
                )
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
            # Убираем N+1: читаем message_reads одной пачкой для всей страницы.
            ordered_rows = list(reversed(rows))
            message_ids = [msg.id for msg, _, _ in ordered_rows]
            sender_by_message_id = {msg.id: int(msg.sender_id) for msg, _, _ in ordered_rows}
            sender_seen_by_other: set[int] = set()
            viewer_seen: set[int] = set()
            if message_ids:
                reads_res = await session.execute(
                    select(MessageRead.message_id, MessageRead.user_id).where(
                        MessageRead.message_id.in_(message_ids)
                    )
                )
                for message_id, reader_id in reads_res.all():
                    sender_id = sender_by_message_id.get(int(message_id))
                    if sender_id is None:
                        continue
                    if int(reader_id) != sender_id:
                        sender_seen_by_other.add(int(message_id))
                    if int(reader_id) == int(user_id):
                        viewer_seen.add(int(message_id))

            for msg, nickname, sender_is_admin in ordered_rows:
                if int(msg.sender_id) == int(user_id):
                    is_read = int(msg.id) in sender_seen_by_other
                else:
                    is_read = int(msg.id) in viewer_seen

                messages.append({
                    "id": msg.id,
                    "room_id": msg.room_id,
                    "sender_id": msg.sender_id,
                    "sender_device_id": msg.sender_device_id,
                    "sender_nickname": nickname,
                    "sender_is_admin": bool(sender_is_admin),
                    "content": msg.content,  # ciphertext
                    "nonce": msg.nonce,
                    "key_version": msg.key_version,
                    "reply_to_message_id": msg.reply_to_message_id,
                    "is_pinned": bool(getattr(msg, "is_pinned", False)),
                    "pinned_by_user_id": getattr(msg, "pinned_by_user_id", None),
                    "pinned_at": msg.pinned_at.isoformat() if getattr(msg, "pinned_at", None) else None,
                    "pin_note": getattr(msg, "pin_note", None),
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
        Возвращает последнее сообщение комнаты

        Нужно для отображения превью в списке чатов ("Последнее: ...")
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
                "content": msg.content,  # ciphertext
                "nonce": msg.nonce,
                "key_version": msg.key_version,
                "sender_device_id": msg.sender_device_id,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }

    # ==========================================================================
    # РЕДАКТИРОВАНИЕ
    # ==========================================================================

    async def edit_message(
        self,
        message_id: int,
        user_id: int,
        new_content: str,
        nonce: str,
        key_version: Optional[int] = None,
    ) -> Message:
        """
        Редактирует текст сообщения.

        Шаги:
        1. Находит сообщение по ID.
        2. Проверяет что текущий пользователь — автор.
        3. Обновляет E2E-поля.
        4. Обновляет поля: content, nonce, key_version, is_edited, edited_at.
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

            # 4. Обновляем поля
            message.content = new_content
            message.nonce = nonce
            if key_version:
                message.key_version = key_version
            message.is_edited = True
            message.edited_at = datetime.utcnow()
            session.add(message)

            # 5. Коммит
            await session.commit()
            await session.refresh(message)
            return message

    async def pin_message(
        self,
        room_id: int,
        message_id: int,
        actor_id: int,
        pin_note: Optional[str] = None,
    ) -> Message:
        async for session in db_engine.get_async_session():
            rights_res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == actor_id,
                )
            )
            member = rights_res.scalars().first()
            if not member or member.status not in (MembershipStatus.OWNER, MembershipStatus.ADMIN):
                raise ValueError("Недостаточно прав для закрепления")

            msg_res = await session.execute(
                select(Message).where(Message.id == message_id, Message.room_id == room_id)
            )
            message = msg_res.scalars().first()
            if not message:
                raise ValueError("Сообщение не найдено")

            message.is_pinned = True
            message.pinned_by_user_id = actor_id
            message.pinned_at = datetime.utcnow()
            message.pin_note = pin_note
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message

    async def unpin_message(self, room_id: int, message_id: int, actor_id: int) -> Message:
        async for session in db_engine.get_async_session():
            rights_res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == actor_id,
                )
            )
            member = rights_res.scalars().first()
            if not member or member.status not in (MembershipStatus.OWNER, MembershipStatus.ADMIN):
                raise ValueError("Недостаточно прав для открепления")

            msg_res = await session.execute(
                select(Message).where(Message.id == message_id, Message.room_id == room_id)
            )
            message = msg_res.scalars().first()
            if not message:
                raise ValueError("Сообщение не найдено")

            message.is_pinned = False
            message.pinned_by_user_id = None
            message.pinned_at = None
            message.pin_note = None
            session.add(message)
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
