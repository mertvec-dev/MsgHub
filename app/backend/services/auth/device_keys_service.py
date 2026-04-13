"""Use-case слой для операций с E2E ключами устройств."""

from datetime import datetime
from typing import Optional

from sqlmodel import select

from database.engine import db_engine
from database.models.devices import Device
from database.models.friendships import Friendship, FriendshipStatus
from database.models.room_member import RoomMember, MembershipStatus
from database.models.rooms import Room, RoomType


class DeviceKeysService:
    """
    Сервис ключей устройств.

    Содержит только операции device-key и проверки доступа к ключам собеседника.
    """

    async def upsert_device_key(
        self,
        user_id: int,
        device_id: str,
        public_key: str,
        algorithm: str,
        *,
        upsert_device_cb,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
    ) -> Device:
        """Сохраняет/обновляет публичный ключ конкретного устройства."""
        async for session in db_engine.get_async_session():
            device = await upsert_device_cb(
                session, user_id, device_id, device_name, device_type
            )
            if device is None:
                raise ValueError("device_id обязателен")
            device.public_key = public_key
            device.key_algorithm = algorithm
            device.key_updated_at = datetime.utcnow()
            session.add(device)
            await session.commit()
            await session.refresh(device)
            return device

    async def get_peer_keys(self, viewer_id: int, peer_user_id: int) -> list[Device]:
        """Возвращает ключи устройств peer-пользователя при наличии прав просмотра."""
        async for session in db_engine.get_async_session():
            friend_res = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == viewer_id) & (Friendship.receiver_id == peer_user_id))
                        | ((Friendship.sender_id == peer_user_id) & (Friendship.receiver_id == viewer_id))
                    ),
                )
            )
            # Доступ разрешен друзьям. Если не друзья — fallback: общий чат.
            if not friend_res.scalars().first() and viewer_id != peer_user_id:
                shared_room = await session.execute(
                    select(RoomMember).where(RoomMember.user_id == viewer_id)
                )
                my_rooms = {row.room_id for row in shared_room.scalars().all()}
                peer_room = await session.execute(
                    select(RoomMember).where(RoomMember.user_id == peer_user_id)
                )
                peer_rooms = {row.room_id for row in peer_room.scalars().all()}
                if not (my_rooms & peer_rooms):
                    raise ValueError("Недостаточно прав для просмотра ключей устройства")

            res = await session.execute(
                select(Device).where(
                    Device.user_id == peer_user_id,
                    Device.public_key.is_not(None),
                )
            )
            return list(res.scalars().all())

    async def get_direct_e2e_readiness(self, viewer_id: int, peer_user_id: int) -> dict:
        """
        Возвращает серверную готовность direct E2E.

        Этот статус используется как источник истины для UI:
        ready=true только когда подтверждены дружба, direct-room и ключи обоих.
        """
        async for session in db_engine.get_async_session():
            friendship_res = await session.execute(
                select(Friendship.id).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == viewer_id) & (Friendship.receiver_id == peer_user_id))
                        | ((Friendship.sender_id == peer_user_id) & (Friendship.receiver_id == viewer_id))
                    ),
                )
            )
            friendship_confirmed = friendship_res.scalars().first() is not None

            direct_room_id = None
            my_direct_rooms = await session.execute(
                select(Room.id)
                .join(RoomMember, RoomMember.room_id == Room.id)
                .where(
                    Room.type == RoomType.DIRECT,
                    RoomMember.user_id == viewer_id,
                    RoomMember.status != MembershipStatus.BANNED,
                )
            )
            for room_id in my_direct_rooms.scalars().all():
                peer_member = await session.execute(
                    select(RoomMember.id).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id == peer_user_id,
                        RoomMember.status != MembershipStatus.BANNED,
                    )
                )
                if peer_member.scalars().first():
                    direct_room_id = int(room_id)
                    break

            viewer_has_key_res = await session.execute(
                select(Device.id).where(
                    Device.user_id == viewer_id,
                    Device.public_key.is_not(None),
                ).limit(1)
            )
            peer_has_key_res = await session.execute(
                select(Device.id).where(
                    Device.user_id == peer_user_id,
                    Device.public_key.is_not(None),
                ).limit(1)
            )
            viewer_has_device_key = viewer_has_key_res.scalars().first() is not None
            peer_has_device_key = peer_has_key_res.scalars().first() is not None

            ready = bool(
                friendship_confirmed
                and direct_room_id is not None
                and viewer_has_device_key
                and peer_has_device_key
            )
            reason = None
            if not friendship_confirmed:
                reason = "friendship_not_confirmed"
            elif direct_room_id is None:
                reason = "direct_room_missing"
            elif not viewer_has_device_key:
                reason = "viewer_device_key_missing"
            elif not peer_has_device_key:
                reason = "peer_device_key_missing"

            return {
                "peer_user_id": peer_user_id,
                "direct_room_id": direct_room_id,
                "friendship_confirmed": friendship_confirmed,
                "viewer_has_device_key": viewer_has_device_key,
                "peer_has_device_key": peer_has_device_key,
                "ready": ready,
                "reason": reason,
            }

