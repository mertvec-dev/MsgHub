"""Admin-use-case слой для операций над пользователями."""

from sqlmodel import select
from sqlalchemy import func, or_, text

from database.engine import db_engine
from database.models.users import User, UserRole
from database.models.rooms import Room
from database.models.messages import Message
from database.models.user_permissions import UserPermission
from database.models.sessions import Session
from database.models.devices import Device
from database.models.users_public_key import UserPublicKey
from database.models.room_key_envelopes import RoomKeyEnvelope
from database.models.message_reads import MessageRead
from database.models.friendships import Friendship
from database.models.room_member import RoomMember
from database.models.security_events import SecurityEvent
from database.models.admin_audit_logs import AdminAuditLog
from sqlalchemy import delete as sql_delete
from app.backend.services.auth.rbac import effective_permissions


def _escape_like_pattern(s: str) -> str:
    """Экранирует %, _ и \\ для LIKE/ILIKE (иначе _ и % — спецсимволы SQL)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AdminService:
    """
    Сервис административных действий.

    Вынесен отдельно, чтобы не держать admin-ветки в общем auth-сервисе.
    """

    async def list_users(self) -> list[User]:
        """Возвращает список всех пользователей в стабильной сортировке."""
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).order_by(User.id.asc()))
            return list(res.scalars().all())

    async def search_users(self, query: str, limit: int = 50) -> list[User]:
        """Поиск по id, username, nickname, profile_tag (без полного скана списка в UI)."""
        raw = (query or "").strip()
        if not raw:
            return []
        if len(raw) > 96:
            raw = raw[:96]
        lim = max(1, min(int(limit), 100))
        async for session in db_engine.get_async_session():
            if raw.isdigit():
                try:
                    uid = int(raw)
                except ValueError:
                    return []
                res = await session.execute(select(User).where(User.id == uid))
                u = res.scalars().first()
                return [u] if u else []
            # @username в UI — ищем без префикса
            needle = raw[1:] if raw.startswith("@") else raw
            if not needle:
                return []
            like = f"%{_escape_like_pattern(needle)}%"
            res = await session.execute(
                select(User)
                .where(
                    or_(
                        User.username.ilike(like, escape="\\"),
                        User.nickname.ilike(like, escape="\\"),
                        User.profile_tag.ilike(like, escape="\\"),
                    )
                )
                .order_by(User.id.asc())
                .limit(lim)
            )
            return list(res.scalars().all())

    async def get_user_extra_permissions(self, user_id: int) -> set[str]:
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(UserPermission.permission).where(UserPermission.user_id == user_id)
            )
            return {str(item) for item in res.scalars().all()}

    async def get_user_effective_permissions(self, user_id: int) -> set[str]:
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == user_id))
            user = res.scalars().first()
            if not user:
                return set()
        extra = await self.get_user_extra_permissions(user_id)
        role = user.role.value if hasattr(user.role, "value") else str(user.role)
        return effective_permissions(role, extra)

    async def get_overview(self) -> dict:
        """Короткая сводка для панели администратора."""
        async for session in db_engine.get_async_session():
            users_total = int((await session.execute(select(func.count(User.id)))).scalar() or 0)
            admins_total = int(
                (await session.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))).scalar() or 0
            )
            banned_total = int(
                (await session.execute(select(func.count(User.id)).where(User.is_banned.is_(True)))).scalar() or 0
            )
            rooms_total = int((await session.execute(select(func.count(Room.id)))).scalar() or 0)
            messages_total = int((await session.execute(select(func.count(Message.id)))).scalar() or 0)
            return {
                "users_total": users_total,
                "admins_total": admins_total,
                "banned_total": banned_total,
                "rooms_total": rooms_total,
                "messages_total": messages_total,
            }

    async def set_admin_flag(self, target_user_id: int, value: bool) -> User:
        """Включает/выключает флаг администратора."""
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            if value:
                user.role = UserRole.MODERATOR
                user.is_admin = True
            else:
                user.role = UserRole.USER
                user.is_admin = False
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def set_role(self, target_user_id: int, role: UserRole) -> User:
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            user.role = role
            user.is_admin = role in (UserRole.MODERATOR, UserRole.SUPER_ADMIN)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def grant_permission(self, target_user_id: int, permission: str) -> None:
        async for session in db_engine.get_async_session():
            user_res = await session.execute(select(User.id).where(User.id == target_user_id))
            if not user_res.first():
                raise ValueError("Пользователь не найден")
            existing_res = await session.execute(
                select(UserPermission).where(
                    UserPermission.user_id == target_user_id,
                    UserPermission.permission == permission,
                )
            )
            if not existing_res.scalars().first():
                session.add(UserPermission(user_id=target_user_id, permission=permission))
                await session.commit()
            return

    async def revoke_permission(self, target_user_id: int, permission: str) -> None:
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(UserPermission).where(
                    UserPermission.user_id == target_user_id,
                    UserPermission.permission == permission,
                )
            )
            item = res.scalars().first()
            if item:
                await session.delete(item)
                await session.commit()
            return

    async def set_profile_tag(self, target_user_id: int, profile_tag: str | None) -> User:
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            user.profile_tag = profile_tag
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def delete_user_account(self, target_user_id: int) -> None:
        async for session in db_engine.get_async_session():
            user_res = await session.execute(select(User).where(User.id == target_user_id))
            user = user_res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")

            # Иначе FK rooms.created_by -> users.id блокирует удаление пользователя
            room_ids_res = await session.execute(select(Room.id).where(Room.created_by == target_user_id))
            for rid in room_ids_res.scalars().all():
                await session.execute(
                    text(
                        """
                        DELETE FROM message_reads WHERE message_id IN (
                            SELECT id FROM messages WHERE room_id = :rid
                        )
                        """
                    ),
                    {"rid": rid},
                )
                await session.execute(
                    text("UPDATE messages SET reply_to_message_id = NULL WHERE room_id = :rid"),
                    {"rid": rid},
                )
                await session.execute(text("DELETE FROM messages WHERE room_id = :rid"), {"rid": rid})
                await session.execute(sql_delete(RoomKeyEnvelope).where(RoomKeyEnvelope.room_id == rid))
                await session.execute(sql_delete(RoomMember).where(RoomMember.room_id == rid))
                await session.execute(sql_delete(Room).where(Room.id == rid))

            await session.execute(sql_delete(MessageRead).where(MessageRead.user_id == target_user_id))
            await session.execute(sql_delete(RoomKeyEnvelope).where(RoomKeyEnvelope.user_id == target_user_id))
            await session.execute(sql_delete(UserPermission).where(UserPermission.user_id == target_user_id))
            await session.execute(sql_delete(UserPublicKey).where(UserPublicKey.user_id == target_user_id))
            await session.execute(sql_delete(Device).where(Device.user_id == target_user_id))
            await session.execute(sql_delete(Session).where(Session.user_id == target_user_id))
            await session.execute(
                sql_delete(Friendship).where(
                    (Friendship.sender_id == target_user_id) | (Friendship.receiver_id == target_user_id)
                )
            )
            await session.execute(
                text("UPDATE room_members SET muted_by_user_id = NULL WHERE muted_by_user_id = :uid"),
                {"uid": target_user_id},
            )
            await session.execute(sql_delete(RoomMember).where(RoomMember.user_id == target_user_id))
            await session.execute(
                sql_delete(Message).where(
                    (Message.sender_id == target_user_id) | (Message.pinned_by_user_id == target_user_id)
                )
            )
            await session.execute(
                sql_delete(SecurityEvent).where(SecurityEvent.user_id == target_user_id)
            )
            await session.execute(
                sql_delete(AdminAuditLog).where(
                    (AdminAuditLog.actor_user_id == target_user_id) | (AdminAuditLog.target_user_id == target_user_id)
                )
            )
            await session.delete(user)
            await session.commit()
            return

    async def set_ban_flag(self, target_user_id: int, value: bool) -> User:
        """Банит/разбанивает пользователя и синхронизирует `is_active`."""
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            user.is_banned = value
            user.is_active = not value
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def set_active_flag(self, target_user_id: int, value: bool) -> User:
        """Меняет активность аккаунта; при деактивации принудительно ставит бан."""
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            user.is_active = value
            if not value:
                user.is_banned = True
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

