"""
Сервис комнат — создание, управление участниками, права

Отвечает за:
  - Создание групповых и личных (direct) комнат
  - Приглашение/кик/бан участников
  - Проверку прав (владелец/админ)
  - Восстановление удалённых direct-чатов
  - Очистку истории сообщений
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from typing import List, Dict, Any
from datetime import datetime

from sqlmodel import select
from sqlalchemy import text

from database.engine import db_engine
from database.models.rooms import Room, RoomType
from database.models.room_member import RoomMember, MembershipStatus
from database.models.friendships import Friendship, FriendshipStatus
from database.models.messages import Message
from database.models.users import User
from database.models.room_key_envelopes import RoomKeyEnvelope
from app.backend.schemas.e2e import RoomKeyEnvelopeUpsertRequest


# ============================================================================
# СЕРВИС
# ============================================================================

class RoomService:
    """
    Управление комнатами и участниками.
    """

    # ==========================================================================
    # СОЗДАНИЕ КОМНАТЫ
    # ==========================================================================

    async def create_room(
        self,
        creator_id: int,
        name: str,
        type: RoomType,
        user_ids: List[int],
    ) -> Room:
        """
        Создаёт новую комнату.

        Шаги:
        1. Создаёт запись Room.
        2. Добавляет создателя как OWNER.
        3. Добавляет приглашённых как MEMBER.

        user_ids — список ID пользователей, которых приглашаем.
        """
        async for session in db_engine.get_async_session():
            # 1. Создаём комнату
            room = Room(name=name, type=type, created_by=creator_id)
            session.add(room)
            await session.flush()  # Получаем room.id, но ещё не коммитим

            # 2. Добавляем участников (создатель + приглашённые)
            member_ids = set(user_ids + [creator_id])
            for uid in member_ids:
                session.add(RoomMember(
                    room_id=room.id,
                    user_id=uid,
                    status=MembershipStatus.OWNER if uid == creator_id else MembershipStatus.MEMBER,
                ))

            await session.commit()
            await session.refresh(room)
            return room

    # ==========================================================================
    # ЛИЧНЫЙ ЧАТ (DIRECT)
    # ==========================================================================

    async def create_direct_room(self, user_id: int, target_user_id: int) -> Room:
        """
        Создаёт или возвращает существующий личный чат.

        Логика:
        1. Проверяет что пользователи — друзья (ACCEPTED).
        2. Ищет комнату где ОБА участника (обычный случай).
        3. Ищет комнату где ВТОРОЙ участник, но текущий удалил себя (восстановление).
        4. Если ничего нет — создаёт новую.

        **Зачем восстановление:**
        Если один из участников удалил чат из своего списка (delete_room_for_self),
        его запись в room_members удалена. Но комната и записи второго участника
        остались. Вместо создания дубликата — восстанавливаем первого участника.
        """
        async for session in db_engine.get_async_session():
            # 1. Проверяем что они друзья
            friend_res = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == user_id) & (Friendship.receiver_id == target_user_id)) |
                        ((Friendship.sender_id == target_user_id) & (Friendship.receiver_id == user_id))
                    ),
                )
            )
            if not friend_res.scalars().first():
                raise ValueError("Можно создать чат только с другом")

            # 2. Ищем комнату где ОБА участника (обычный случай)
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
                    return room  # Оба на месте — возвращаем

            # 3. Ищем комнату где ВТОРОЙ участник (восстановление после удаления)
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
                    # Восстанавливаем пользователя в чате
                    session.add(RoomMember(
                        room_id=room.id,
                        user_id=user_id,
                        status=MembershipStatus.MEMBER,
                    ))
                    await session.commit()
                    await session.refresh(room)
                    return room

            # 4. Создаём новую комнату
            room = Room(name=None, type=RoomType.DIRECT, created_by=user_id)
            session.add(room)
            await session.flush()

            session.add_all([
                RoomMember(room_id=room.id, user_id=user_id, status=MembershipStatus.MEMBER),
                RoomMember(room_id=room.id, user_id=target_user_id, status=MembershipStatus.MEMBER),
            ])
            await session.commit()
            await session.refresh(room)
            return room

    # ==========================================================================
    # ПРИГЛАШЕНИЕ
    # ==========================================================================

    async def invite_to_room(self, room_id: int, user_id: int, actor_id: int) -> dict:
        """
        Приглашает пользователя в комнату.

        **Для групповых комнат:**
        - Проверяет права actor_id (админ/владелец).
        - Проверяет что приглашаемые — друзья actor_id.
        - Добавляет как MEMBER.

        **Для direct комнат:**
        - Direct = только 2 участника, нельзя пригласить третьего.
        - Вместо этого создаёт новую ГРУППОВУЮ комнату с обоими участниками + новым.
        """
        async for session in db_engine.get_async_session():
            if not await self._check_rights(actor_id, room_id, session):
                raise ValueError("Прав недостаточно")

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()

            # Direct-чат нельзя расширить — создаём группу
            if room.type == RoomType.DIRECT:
                members_res = await session.execute(
                    select(RoomMember.user_id).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id != actor_id,
                    )
                )
                partner_id = members_res.scalar()

                new_room = Room(
                    name=f"Группа {actor_id} и {partner_id}",
                    type=RoomType.GROUP,
                    created_by=actor_id,
                )
                session.add(new_room)
                await session.flush()

                for uid in [actor_id, partner_id, user_id]:
                    status = MembershipStatus.OWNER if uid == actor_id else MembershipStatus.MEMBER
                    session.add(RoomMember(room_id=new_room.id, user_id=uid, status=status))

                await session.commit()
                return {"status": "group_created", "new_room_id": new_room.id}

            # Проверяем что приглашаемый — друг
            f_res = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == actor_id) & (Friendship.receiver_id == user_id)) |
                        ((Friendship.sender_id == user_id) & (Friendship.receiver_id == actor_id))
                    ),
                )
            )
            if not f_res.scalars().first():
                raise ValueError("Можно звать только друзей!")

            # Проверяем что ещё не в комнате
            check = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            if check.scalars().first():
                raise ValueError("Уже в комнате!")

            session.add(RoomMember(
                room_id=room_id,
                user_id=user_id,
                status=MembershipStatus.MEMBER,
            ))
            await session.commit()
            return {"status": "invited"}

    # ==========================================================================
    # КИК
    # ==========================================================================

    async def del_user_from_room(self, room_id: int, user_id: int, actor_id: int) -> bool:
        """
        Выгоняет участника из комнаты.

        Проверки:
        - actor_id имеет права (админ/владелец).
        - user_id состоит в комнате.
        - Нельзя кикнуть владельца.
        """
        async for session in db_engine.get_async_session():
            if not await self._check_rights(actor_id, room_id, session):
                raise ValueError("Прав недостаточно")

            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            member = res.scalars().first()
            if not member:
                raise ValueError("Нет в комнате")

            if member.status == MembershipStatus.OWNER:
                raise ValueError("Нельзя кикнуть владельца")

            await session.delete(member)
            await session.commit()
            return True

    # ==========================================================================
    # ВЫХОД ИЗ КОМНАТЫ
    # ==========================================================================

    async def exit_from_room(self, room_id: int, user_id: int) -> bool:
        """
        Пользователь сам выходит из комнаты.

        **Для групповых:**
        - Если OWNER — удаляет всю комнату (все участники, все сообщения).
        - Если MEMBER — удаляет только свою запись.

        **Для direct:**
        - Нельзя выйти — используйте «очистить историю».
        """
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            member = res.scalars().first()
            if not member:
                raise ValueError("Нет в комнате")

            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()

            # Direct-чат нельзя покинуть
            if room and room.type == RoomType.DIRECT:
                raise ValueError("Нельзя покинуть личный чат. Используйте очистку истории.")

            # Владелец уходит — удаляем всю комнату
            if member.status == MembershipStatus.OWNER:
                await session.delete(room)
            else:
                await session.delete(member)

            await session.commit()
            return True

    # ==========================================================================
    # ОЧИСТКА ИСТОРИИ
    # ==========================================================================

    async def clear_history(self, room_id: int, user_id: int) -> bool:
        """
        Очищает историю сообщений в комнате **только для текущего пользователя**.

        Логика:
        1. Удаляет записи о прочтении своих сообщений.
        2. Удаляет свои сообщения из комнаты.
        3. Сообщения других участников остаются нетронутыми.
        """
        async for session in db_engine.get_async_session():
            member_res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id, RoomMember.user_id == user_id
                )
            )
            if not member_res.scalars().first():
                raise ValueError("Вы не участник этой комнаты")

            # 1. Удаляем записи о прочтении СВОИХ сообщений
            await session.execute(
                text("""
                    DELETE FROM message_reads 
                    WHERE message_id IN (SELECT id FROM messages WHERE room_id = :rid AND sender_id = :uid)
                """),
                {"rid": room_id, "uid": user_id},
            )
            # 2. Удаляем только СВОИ сообщения
            await session.execute(
                text("DELETE FROM messages WHERE room_id = :rid AND sender_id = :uid"),
                {"rid": room_id, "uid": user_id},
            )

            await session.commit()
            return True

    # ==========================================================================
    # УДАЛЕНИЕ КОМНАТЫ ДЛЯ СЕБЯ
    # ==========================================================================

    async def delete_room_for_self(self, room_id: int, user_id: int) -> bool:
        """
        Скрывает комнату из списка текущего пользователя.

        Удаляет запись участника из room_members.
        Комната продолжает существовать для других участников.
        """
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            member = res.scalars().first()
            if not member:
                raise ValueError("Вы не участник этой комнаты")

            await session.delete(member)
            await session.commit()
            return True

    # ==========================================================================
    # БАН / РАЗБАН
    # ==========================================================================

    async def ban_user(self, room_id: int, user_id: int, actor_id: int) -> bool:
        """
        Блокирует участника — меняет статус на BANNED.

        Забаненный:
        - Не видит комнату в списке.
        - Не может получить сообщения.
        """
        async for session in db_engine.get_async_session():
            if not await self._check_rights(actor_id, room_id, session):
                raise ValueError("Прав недостаточно")

            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            member = res.scalars().first()
            if not member:
                raise ValueError("Пользователь не в комнате")

            member.status = MembershipStatus.BANNED
            await session.commit()
            return True

    async def unban_user(self, room_id: int, user_id: int, actor_id: int) -> bool:
        """
        Разблокирует участника — возвращает статус MEMBER.
        """
        async for session in db_engine.get_async_session():
            if not await self._check_rights(actor_id, room_id, session):
                raise ValueError("Прав недостаточно")

            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                )
            )
            member = res.scalars().first()
            if not member:
                raise ValueError("Пользователь не в комнате")

            if member.status != MembershipStatus.BANNED:
                raise ValueError("Пользователь не заблокирован")

            member.status = MembershipStatus.MEMBER
            await session.commit()
            return True

    # ==========================================================================
    # СПИСОК КОМНАТ С ПРЕВЬЮ
    # ==========================================================================

    async def get_user_rooms(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает комнаты пользователя с превью последнего сообщения.

        **Формат ответа:**
        [
          {
            "id": 1,
            "name": "Общий чат",
            "type": "group",
            "last_message": "Привет!",
            "last_message_sender": "Алексей",
            "updated_at": "2026-04-04T...",
            ...
          },
          ...
        ]

        Сортировка: по updated_at (последнее сообщение — сверху).
        """
        async for session in db_engine.get_async_session():
            # 1. Получаем комнаты (исключая забаненных)
            res = await session.execute(
                select(Room)
                .join(RoomMember)
                .where(
                    RoomMember.user_id == user_id,
                    RoomMember.status != MembershipStatus.BANNED,
                )
                .order_by(Room.updated_at.desc())
            )
            rooms_list = res.scalars().all()

            # 2. Для каждой комнаты — превью последнего сообщения
            result_data = []
            for room in rooms_list:
                preview_res = await session.execute(
                    select(Message.content, User.nickname)
                    .join(User, Message.sender_id == User.id)
                    .where(Message.room_id == room.id)
                    .order_by(Message.id.desc())
                    .limit(1)
                )
                preview_row = preview_res.first()

                room_dict = {
                    "id": room.id,
                    "name": room.name,
                    "type": room.type,
                    "created_by": room.created_by,
                    "created_at": room.created_at,
                    "updated_at": room.updated_at,
                    "last_message": preview_row.content if preview_row else None,
                    "last_message_sender": preview_row.nickname if preview_row else None,
                }
                if room.type == RoomType.DIRECT:
                    other_res = await session.execute(
                        select(User)
                        .join(RoomMember, User.id == RoomMember.user_id)
                        .where(
                            RoomMember.room_id == room.id,
                            RoomMember.user_id != user_id,
                        )
                    )
                    other = other_res.scalars().first()
                    if other:
                        room_dict["partner_id"] = other.id
                        room_dict["partner_nickname"] = other.nickname
                        room_dict["partner_username"] = other.username

                result_data.append(room_dict)

            return result_data

    # ==========================================================================
    # ПРОВЕРКА ПРАВ (ВНУТРЕННИЙ МЕТОД)
    # ==========================================================================

    async def _check_rights(self, user_id: int, room_id: int, session) -> bool:
        """
        Проверяет что user_id — админ или владелец в room_id.

        Используется внутри сервисов для защиты операций
        (приглашение, кик, бан).
        """
        res = await session.execute(
            select(RoomMember).where(
                (RoomMember.user_id == user_id) & (RoomMember.room_id == room_id)
            )
        )
        member = res.scalars().first()
        return member and member.status in (MembershipStatus.ADMIN, MembershipStatus.OWNER)

    # ==========================================================================
    # ОБНОВЛЕНИЕ КОНВЕРТА С ПУБЛИЧНЫМ КЛЮЧОМ E2E ДЛЯ ШИФРОВАНИЯ СООБЩЕНИЙ В КОМНАТЕ
    # ==========================================================================

    async def upsert_room_key(self, room_id: int, user_id: int, request: RoomKeyEnvelopeUpsertRequest) -> dict:
        """
        Пакетно сохраняет/обновляет конверты room key для указанной версии ключа.
        """
        async for session in db_engine.get_async_session():
            # 1) Текущий пользователь должен быть участником комнаты.
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                    RoomMember.status != MembershipStatus.BANNED,
                    )
                )
            member = res.scalars().first()
            if not member:
                raise ValueError("Вы не являетесь участником комнаты")

            # 2) Комната должна существовать.
            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if not room:
                raise ValueError("Комната не найдена")

            # 3) Версия ключа не может быть старее/новее текущей (ротация отдельным шагом).
            if request.key_version < room.current_key_version:
                raise ValueError("Указана устаревшая версия ключа")
            if request.key_version > room.current_key_version:
                raise ValueError("Сначала выполните ротацию ключа комнаты")

            upserted = 0

            # 4) Upsert для каждого конверта из запроса.
            for item in request.envelopes:
                target_member_res = await session.execute(
                    select(RoomMember).where(
                        RoomMember.room_id == room_id,
                        RoomMember.user_id == item.user_id,
                        RoomMember.status != MembershipStatus.BANNED,
                    )
                )
                target_member = target_member_res.scalars().first()
                if not target_member:
                    raise ValueError(f"Пользователь {item.user_id} не является участником комнаты")

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
                    envelope = RoomKeyEnvelope(
                        room_id=room_id,
                        user_id=item.user_id,
                        key_version=request.key_version,
                        encrypted_key=item.encrypted_key,
                        algorithm=item.algorithm,
                    )
                    session.add(envelope)
                upserted += 1

            await session.commit()
            return {
                "room_id": room_id,
                "key_version": request.key_version,
                "upserted": upserted,
            }

    async def get_room_key(self, room_id: int, user_id: int) -> dict:
        """
        Получает конверт с публичным ключом E2E для шифрования сообщений в комнате.
        """
        async for session in db_engine.get_async_session():
            # 1) Текущий пользователь должен быть участником комнаты.
            res = await session.execute(
                select(RoomMember).where(
                    RoomMember.room_id == room_id,
                    RoomMember.user_id == user_id,
                    RoomMember.status != MembershipStatus.BANNED,
                    )
                )
            member = res.scalars().first()
            if not member:
                raise ValueError("Вы не являетесь участником комнаты")

            # 2) Комната должна существовать.
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

    async def rotate_room_key(self, room_id: int, user_id: int) -> dict:
        """
        Вращает (меняет версию) ключ в конверте с публичным ключом E2E для шифрования сообщений в комнате.
        """
        async for session in db_engine.get_async_session():
            # 1) Пользователь должен иметь права администратора или владельца комнаты.
            if not await self._check_rights(user_id, room_id, session):
                raise ValueError("Прав недостаточно")
            
            # 2) Комната должна существовать.
            room_res = await session.execute(select(Room).where(Room.id == room_id))
            room = room_res.scalars().first()
            if not room:
                raise ValueError("Комната не найдена")
            
            # 3) Вращаем ключ.
            room_id_value = room.id
            new_key_version = room.current_key_version + 1
            room.current_key_version = new_key_version
            session.add(room)
            await session.commit()
            # Сервис возвращает plain dict; Pydantic-обертка создается в роутере.
            return {
                "room_id": room_id_value,
                "current_key_version": new_key_version,
            }
# Глобальный экземпляр
room_service = RoomService()
