"""Use-case операций с room key envelopes."""

from datetime import datetime
from typing import Awaitable, Callable

from sqlmodel import select

from app.backend.schemas.e2e import RoomKeyEnvelopeUpsertRequest
from database.engine import db_engine
from database.models.room_key_envelopes import RoomKeyEnvelope
from database.models.room_member import MembershipStatus, RoomMember
from database.models.rooms import Room


class RoomKeyUseCase:
    """Инкапсулирует upsert/get/rotate для ключей комнаты."""

    async def upsert(
        self,
        room_id: int,
        user_id: int,
        request: RoomKeyEnvelopeUpsertRequest,
    ) -> dict:
        """Пакетно upsert конвертов для текущей версии ключа комнаты."""
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                    RoomMember.status != MembershipStatus.BANNED,
                )
            )
            if not res.scalars().first():
                raise ValueError("Вы не являетесь участником комнаты")

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if not room:
                raise ValueError("Комната не найдена")

            if request.key_version < room.current_key_version:
                raise ValueError("Указана устаревшая версия ключа")
            if request.key_version > room.current_key_version:
                raise ValueError("Сначала выполните ротацию ключа комнаты")

            upserted = 0
            for item in request.envelopes:
                target_member_res = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id == item.user_id,
                        RoomMember.status != MembershipStatus.BANNED,
                    )
                )
                if not target_member_res.scalars().first():
                    raise ValueError(
                        f"Пользователь {item.user_id} не является участником комнаты"
                    )

                env_res = await session.execute(
                    select(RoomKeyEnvelope).where(
                        RoomKeyEnvelope.room_id == room_id,
                        RoomKeyEnvelope.user_id == item.user_id,
                        RoomKeyEnvelope.key_version == request.key_version,
                    )
                )
                envelope = env_res.scalars().first()

                if envelope:
                    envelope.encrypted_key = item.encrypted_key
                    envelope.algorithm = item.algorithm
                    envelope.updated_at = datetime.utcnow()
                else:
                    session.add(
                        RoomKeyEnvelope(
                            room_id=room_id,
                            user_id=item.user_id,
                            key_version=request.key_version,
                            encrypted_key=item.encrypted_key,
                            algorithm=item.algorithm,
                        )
                    )
                upserted += 1

            await session.commit()
            return {"room_id": room_id, "key_version": request.key_version, "upserted": upserted}

    async def get_my_key(self, room_id: int, user_id: int) -> dict:
        """Возвращает актуальный room key envelope для текущего пользователя."""
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                    RoomMember.status != MembershipStatus.BANNED,
                )
            )
            if not res.scalars().first():
                raise ValueError("Вы не являетесь участником комнаты")

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if not room:
                raise ValueError("Комната не найдена")

            env_res = await session.execute(
                select(RoomKeyEnvelope).where(
                    RoomKeyEnvelope.room_id == room_id,
                    RoomKeyEnvelope.user_id == user_id,
                    RoomKeyEnvelope.key_version == room.current_key_version,
                )
            )
            envelope = env_res.scalars().first()
            if not envelope:
                raise ValueError("Конверт не найден")
            return {
                "room_id": room_id,
                "user_id": user_id,
                "key_version": room.current_key_version,
                "encrypted_key": envelope.encrypted_key,
                "algorithm": envelope.algorithm,
            }

    async def rotate(
        self,
        room_id: int,
        user_id: int,
        check_rights: Callable[[int, int, object], Awaitable[bool]],
    ) -> dict:
        """Повышает версию ключа комнаты для admin/owner."""
        async for session in db_engine.get_async_session():
            if not await check_rights(user_id, room_id, session):
                raise ValueError("Прав недостаточно")

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if not room:
                raise ValueError("Комната не найдена")

            room_id_value = room.id
            new_key_version = room.current_key_version + 1
            room.current_key_version = new_key_version
            session.add(room)
            await session.commit()
            return {
                "room_id": room_id_value,
                "current_key_version": new_key_version,
            }

