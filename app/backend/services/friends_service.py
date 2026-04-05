"""
Сервис друзей — заявки, принятие, отклонение, удаление

Управляет таблицей Friendship со статусами:
  - PENDING  — заявка отправлена
  - ACCEPTED — дружба подтверждена
  - BLOCKED  — заблокирован
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from datetime import datetime
from typing import List

from sqlmodel import select

from database.engine import db_engine
from database.models.users import User
from database.models.friendships import Friendship, FriendshipStatus


# ============================================================================
# СЕРВИС
# ============================================================================

class FriendsService:
    """
    Управление дружескими связями.
    """

    # ==========================================================================
    # ОТПРАВКА ЗАЯВКИ
    # ==========================================================================

    async def send_request(self, sender_id: int, receiver_username: str) -> bool:
        """
        Создаёт заявку в друзья.

        Шаги:
        1. Ищет пользователя по username.
        2. Проверяет что не себе и не дубликат.
        3. Создаёт запись Friendship со статусом PENDING.
        """
        async for session in db_engine.get_async_session():
            # 1. Ищем получателя
            result = await session.execute(
                select(User).where(User.username == receiver_username)
            )
            receiver = result.scalars().first()

            if not receiver:
                raise ValueError("Пользователь не найден")
            if receiver.id == sender_id:
                raise ValueError("Нельзя добавить себя в друзья")

            # 2. Проверяем существующие связи (в обе стороны)
            result = await session.execute(
                select(Friendship).where(
                    (
                        (Friendship.sender_id == sender_id) & (Friendship.receiver_id == receiver.id)
                    ) | (
                        (Friendship.sender_id == receiver.id) & (Friendship.receiver_id == sender_id)
                    )
                )
            )
            existing = result.scalars().first()

            if existing:
                # Определяем почему нельзя создать заявку
                if existing.status == FriendshipStatus.ACCEPTED:
                    raise ValueError("Вы уже друзья")
                elif existing.status == FriendshipStatus.PENDING:
                    raise ValueError("Заявка уже существует")
                elif existing.status == FriendshipStatus.BLOCKED:
                    raise ValueError("Нельзя отправить заявку (заблокирован)")

            # 3. Создаём заявку
            new_req = Friendship(
                sender_id=sender_id,
                receiver_id=receiver.id,
                status=FriendshipStatus.PENDING,
            )
            session.add(new_req)
            await session.commit()
            return True

    # ==========================================================================
    # ПРИНЯТИЕ ЗАЯВКИ
    # ==========================================================================

    async def accept_request(self, user_id: int, request_id: int) -> bool:
        """
        Принимает входящую заявку.

        Проверяет что:
        - Заявка существует.
        - Текущий пользователь — получатель (не кто угодно может принять).
        - Статус всё ещё PENDING.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    Friendship.id == request_id,
                    Friendship.receiver_id == user_id,
                    Friendship.status == FriendshipStatus.PENDING,
                )
            )
            friendship = result.scalars().first()

            if not friendship:
                raise ValueError("Заявка не найдена или уже обработана")

            friendship.status = FriendshipStatus.ACCEPTED
            friendship.updated_at = datetime.utcnow()
            await session.commit()
            return True

    # ==========================================================================
    # ОТКЛОНЕНИЕ ЗАЯВКИ
    # ==========================================================================

    async def decline_request(self, user_id: int, request_id: int) -> bool:
        """
        Отклоняет входящую заявку — полностью удаляет запись.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    Friendship.id == request_id,
                    Friendship.receiver_id == user_id,
                    Friendship.status == FriendshipStatus.PENDING,
                )
            )
            friendship = result.scalars().first()

            if not friendship:
                raise ValueError("Заявка не найдена")

            await session.delete(friendship)
            await session.commit()
            return True

    # ==========================================================================
    # УДАЛЕНИЕ ИЗ ДРУЗЕЙ
    # ==========================================================================

    async def remove_friend(self, user_id: int, friend_id: int) -> bool:
        """
        Полностью удаляет связь дружбы.

        Ищет запись где user_id и friend_id — sender/receiver (в любом порядке).
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    (
                        (Friendship.sender_id == user_id) & (Friendship.receiver_id == friend_id)
                    ) | (
                        (Friendship.sender_id == friend_id) & (Friendship.receiver_id == user_id)
                    ),
                    Friendship.status == FriendshipStatus.ACCEPTED,
                )
            )
            friendship = result.scalars().first()

            if not friendship:
                raise ValueError("Пользователь не в списке друзей")

            await session.delete(friendship)
            await session.commit()
            return True

    # ==========================================================================
    # БЛОКИРОВКА
    # ==========================================================================

    async def block_user(self, user_id: int, target_user_id: int) -> bool:
        """
        Блокирует пользователя: помечает связь как BLOCKED (или создаёт новую).
        Дальнейшие заявки в друзья от заблокированной стороны не принимаются.
        """
        if user_id == target_user_id:
            raise ValueError("Нельзя заблокировать себя")

        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    (
                        (Friendship.sender_id == user_id)
                        & (Friendship.receiver_id == target_user_id)
                    )
                    | (
                        (Friendship.sender_id == target_user_id)
                        & (Friendship.receiver_id == user_id)
                    )
                )
            )
            friendship = result.scalars().first()

            if friendship:
                friendship.status = FriendshipStatus.BLOCKED
                friendship.updated_at = datetime.utcnow()
            else:
                session.add(
                    Friendship(
                        sender_id=user_id,
                        receiver_id=target_user_id,
                        status=FriendshipStatus.BLOCKED,
                    )
                )
            await session.commit()
            return True

    # ==========================================================================
    # СПИСКИ
    # ==========================================================================

    async def get_friends(self, user_id: int) -> List[Friendship]:
        """Возвращает подтверждённые дружбы (ACCEPTED) пользователя."""
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    (
                        (Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)
                    ),
                    Friendship.status == FriendshipStatus.ACCEPTED,
                )
            )
            return result.scalars().all()

    async def get_pending_requests(self, user_id: int) -> List[Friendship]:
        """Возвращает входящие заявки (PENDING, где пользователь — получатель)."""
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    Friendship.receiver_id == user_id,
                    Friendship.status == FriendshipStatus.PENDING,
                )
            )
            return result.scalars().all()


# Глобальный экземпляр
friends_service = FriendsService()
