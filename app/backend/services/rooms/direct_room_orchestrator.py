"""Оркестрация создания и восстановления direct-комнат."""

from sqlmodel import select

from database.engine import db_engine
from database.models.friendships import Friendship, FriendshipStatus
from database.models.room_member import MembershipStatus, RoomMember
from database.models.rooms import Room, RoomType


class DirectRoomOrchestrator:
    """
    Управляет жизненным циклом direct-комнаты между двумя пользователями.

    Вынесен из `RoomService`, чтобы изолировать правила direct-flow.
    """

    async def create_or_restore(self, user_id: int, target_user_id: int) -> Room:
        """Создает direct-комнату или восстанавливает удаленного участника."""
        async for session in db_engine.get_async_session():
            friend_res = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == user_id) & (Friendship.receiver_id == target_user_id))
                        | ((Friendship.sender_id == target_user_id) & (Friendship.receiver_id == user_id))
                    ),
                )
            )
            if not friend_res.scalars().first():
                raise ValueError("Можно создать чат только с другом")

            my_rooms_res = await session.execute(
                select(Room).join(RoomMember).where(
                    Room.type == RoomType.DIRECT,
                    RoomMember.user_id == user_id,
                )
            )
            for room in my_rooms_res.scalars().all():
                check = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room.id,
                        RoomMember.user_id == target_user_id,
                    )
                )
                if check.scalars().first():
                    return room

            target_rooms_res = await session.execute(
                select(Room).join(RoomMember).where(
                    Room.type == RoomType.DIRECT,
                    RoomMember.user_id == target_user_id,
                )
            )
            for room in target_rooms_res.scalars().all():
                self_check = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room.id,
                        RoomMember.user_id == user_id,
                    )
                )
                if not self_check.scalars().first():
                    session.add(
                        RoomMember(
                            room_id=room.id,
                            user_id=user_id,
                            status=MembershipStatus.MEMBER,
                        )
                    )
                    await session.commit()
                    await session.refresh(room)
                    return room

            room = Room(name=None, type=RoomType.DIRECT, created_by=user_id)
            session.add(room)
            await session.flush()
            session.add_all(
                [
                    RoomMember(room_id=room.id, user_id=user_id, status=MembershipStatus.MEMBER),
                    RoomMember(
                        room_id=room.id,
                        user_id=target_user_id,
                        status=MembershipStatus.MEMBER,
                    ),
                ]
            )
            await session.commit()
            await session.refresh(room)
            return room

