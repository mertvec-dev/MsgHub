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
from database.models.rooms import Room, RoomType
from database.models.room_member import RoomMember, MembershipStatus
from app.backend.services.rooms_service import room_service
from app.backend.domain.errors import ConflictError, NotFoundError, ForbiddenError


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

    async def send_request(self, sender_id: int, receiver_username: str) -> dict:
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
                raise NotFoundError("Пользователь не найден")
            if receiver.id == sender_id:
                raise ConflictError("Нельзя добавить себя в друзья")

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
                    raise ConflictError("Вы уже друзья")
                elif existing.status == FriendshipStatus.PENDING:
                    raise ConflictError("Заявка уже существует")
                elif existing.status == FriendshipStatus.BLOCKED:
                    raise ForbiddenError("Нельзя отправить заявку (заблокирован)")

            # 3. Создаём заявку
            new_req = Friendship(
                sender_id=sender_id,
                receiver_id=receiver.id,
                status=FriendshipStatus.PENDING,
            )
            session.add(new_req)
            await session.commit()
            return {
                "request_id": int(new_req.id),
                "peer_id": int(receiver.id),
            }

    # ==========================================================================
    # ПРИНЯТИЕ ЗАЯВКИ
    # ==========================================================================

    async def accept_request(self, user_id: int, request_id: int) -> dict:
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
                raise NotFoundError("Заявка не найдена или уже обработана")

            sender_id = friendship.sender_id
            friendship.status = FriendshipStatus.ACCEPTED
            friendship.updated_at = datetime.utcnow()
            await session.commit()
            # Автосоздание direct-диалога после принятия дружбы.
            direct_room = await room_service.create_direct_room(user_id, sender_id)
            return {
                "peer_id": sender_id,
                "room_id": direct_room.id,
            }

    # ==========================================================================
    # ОТКЛОНЕНИЕ ЗАЯВКИ
    # ==========================================================================

    async def decline_request(self, user_id: int, request_id: int) -> dict:
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
                raise NotFoundError("Заявка не найдена")

            sender_id = int(friendship.sender_id)
            await session.delete(friendship)
            await session.commit()
            return {"peer_id": sender_id}

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
                raise NotFoundError("Пользователь не в списке друзей")

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
            raise ConflictError("Нельзя заблокировать себя")

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
                friendship.sender_id = user_id
                friendship.receiver_id = target_user_id
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

    async def unblock_user(self, user_id: int, target_user_id: int) -> bool:
        """
        Снимает блокировку, если её поставил текущий пользователь.

        После разблокировки связь удаляется полностью, чтобы не было скрытых
        состояний дружбы/заявок. При необходимости пользователь отправит заявку заново.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    Friendship.sender_id == user_id,
                    Friendship.receiver_id == target_user_id,
                    Friendship.status == FriendshipStatus.BLOCKED,
                )
            )
            friendship = result.scalars().first()
            if not friendship:
                raise NotFoundError("Пользователь не найден в вашем ЧС")
            await session.delete(friendship)
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

    async def get_accepted_peer_ids(self, user_id: int) -> list[int]:
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        (Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)
                    ),
                )
            )
            rows = result.scalars().all()
            peer_ids: list[int] = []
            for item in rows:
                peer_ids.append(
                    int(item.sender_id) if int(item.receiver_id) == int(user_id) else int(item.receiver_id)
                )
            return peer_ids

    async def get_friends_overview(self, user_id: int, is_online_cb) -> list[dict]:
        """
        Возвращает полный список связей дружбы с данными партнера.

        Здесь сосредоточена SQL-логика списка друзей, чтобы роутер оставался тонким.
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(Friendship).where(
                    (Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)
                )
            )
            friendships = result.scalars().all()

            response: list[dict] = []
            for friendship in friendships:
                partner_id = (
                    friendship.sender_id
                    if friendship.receiver_id == user_id
                    else friendship.receiver_id
                )

                partner_result = await session.execute(select(User).where(User.id == partner_id))
                partner = partner_result.scalars().first()

                response.append(
                    {
                        "id": friendship.id,
                        "partner_id": partner_id,
                        "nickname": partner.nickname if partner else f"User#{partner_id}",
                        "username": partner.username if partner else "unknown",
                        "is_admin": bool(partner.is_admin) if partner else False,
                        "status": friendship.status,
                        "blocked_by_me": friendship.status == FriendshipStatus.BLOCKED
                        and int(friendship.sender_id) == int(user_id),
                        "sender_id": friendship.sender_id,
                        "receiver_id": friendship.receiver_id,
                        "is_online": is_online_cb(partner_id),
                        "created_at": friendship.created_at.isoformat()
                        if friendship.created_at
                        else None,
                    }
                )

            return response

    async def enforce_block_for_direct_chat(self, actor_id: int, target_user_id: int) -> list[int]:
        """
        Применяет блокировку к существующим direct-чатам пары и возвращает их room_id.

        Нужно, чтобы после блокировки:
        - чат исчезал из списков,
        - отправка/чтение через API прекращались.
        """
        affected_room_ids: list[int] = []
        async for session in db_engine.get_async_session():
            direct_rooms_res = await session.execute(
                select(Room.id)
                .join(RoomMember, RoomMember.room_id == Room.id)
                .where(
                    Room.type == RoomType.DIRECT,
                    RoomMember.user_id == actor_id,
                )
            )
            for room_id in [int(rid) for rid in direct_rooms_res.scalars().all()]:
                peer_member_res = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id == target_user_id,
                    )
                )
                peer_member = peer_member_res.scalars().first()
                if not peer_member:
                    continue
                affected_room_ids.append(room_id)

                actor_member_res = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id == actor_id,
                    )
                )
                actor_member = actor_member_res.scalars().first()
                if actor_member:
                    actor_member.status = MembershipStatus.BANNED
                    session.add(actor_member)

                peer_member.status = MembershipStatus.BANNED
                session.add(peer_member)

            await session.commit()
            return affected_room_ids


# Глобальный экземпляр
friends_service = FriendsService()
