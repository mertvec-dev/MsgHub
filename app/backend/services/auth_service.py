import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sql_delete
from sqlmodel import select

from app.backend.config import settings
from app.backend.utils.jwt_utils import create_access_token
from app.backend.utils.password_validator import hash_password, validate_password, verify_password
from database.engine import db_engine
from database.models.devices import Device
from database.models.friendships import Friendship
from database.models.room_member import RoomMember
from database.models.messages import Message
from database.models.sessions import Session as SessionModel
from database.models.users import User, UserRole
from database.models.users_public_key import UserPublicKey
from database.redis import redis_client
from app.backend.services.auth.admin_service import AdminService
from app.backend.services.auth.device_keys_service import DeviceKeysService
from app.backend.services.auth.profile_service import ProfileService
from app.backend.services.auth.sessions_service import SessionsService
from app.backend.services.auth.rbac import Permission, has_permission
from app.backend.services.audit_log_service import audit_log_service

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self) -> None:
        # Декомпозиция "толстого" auth-сервиса на прикладные зоны.
        self.admin_service = AdminService()
        self.device_keys_service = DeviceKeysService()
        self.profile_service = ProfileService()
        self.sessions_service = SessionsService()

    @staticmethod
    def _token_hash(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode()).hexdigest()

    async def _cache_session(self, token_hash: str, user_id: int) -> None:
        try:
            await redis_client.set(
                f"session:{token_hash}",
                str(user_id),
                ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            )
        except Exception:
            logger.warning("Не удалось сохранить сессию в Redis")

    async def _upsert_device(
        self,
        session: AsyncSession,
        user_id: int,
        device_id: Optional[str],
        device_name: Optional[str],
        device_type: Optional[str],
    ) -> Optional[Device]:
        if not device_id:
            return None
        res = await session.execute(
            select(Device).where(Device.user_id == user_id, Device.device_id == device_id)
        )
        device = res.scalars().first()
        if not device:
            device = Device(
                user_id=user_id,
                device_id=device_id,
                device_name=device_name,
                device_type=device_type,
                last_active_at=datetime.utcnow(),
            )
        else:
            if device_name:
                device.device_name = device_name
            if device_type:
                device.device_type = device_type
            device.last_active_at = datetime.utcnow()
        session.add(device)
        return device

    async def _sanitize_new_user_state(self, session: AsyncSession, user_id: int) -> None:
        """
        Защитная очистка следов для нового user_id.

        Нужна как fail-safe на случай неконсистентной БД/ручных миграций:
        новый аккаунт не должен «унаследовать» старые дружбы, комнаты и ключи.
        """
        await session.execute(
            sql_delete(Friendship).where(
                (Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)
            )
        )
        await session.execute(sql_delete(RoomMember).where(RoomMember.user_id == user_id))
        await session.execute(sql_delete(Message).where(Message.sender_id == user_id))
        await session.execute(sql_delete(SessionModel).where(SessionModel.user_id == user_id))
        await session.execute(sql_delete(Device).where(Device.user_id == user_id))
        await session.execute(sql_delete(UserPublicKey).where(UserPublicKey.user_id == user_id))

    async def register(
        self,
        nickname: str,
        username: str,
        password: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> dict:
        if not validate_password(password):
            raise ValueError("Слабый пароль")

        async with AsyncSession(db_engine.engine) as session:
            users_count_res = await session.execute(select(User.id))
            is_first_user = users_count_res.first() is None
            for condition, msg in (
                (User.nickname == nickname, "Nickname уже занят"),
                (User.username == username, "Username уже занят"),
            ):
                res = await session.execute(select(User).where(condition))
                if res.scalars().first():
                    raise ValueError(msg)

            user = User(
                nickname=nickname,
                username=username,
                password_hash=hash_password(password),
                role=UserRole.SUPER_ADMIN if is_first_user else UserRole.USER,
                is_admin=is_first_user,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await self._sanitize_new_user_state(session, user_id)

            await self._upsert_device(session, user_id, device_id, device_name, device_type)

            refresh_token = secrets.token_urlsafe(32)
            refresh_token_hash = self._token_hash(refresh_token)
            expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
            session.add(
                SessionModel(
                    user_id=user_id,
                    refresh_token_hash=refresh_token_hash,
                    device_id=device_id,
                    device_info=device_name or "Unknown",
                    ip_address=ip_address,
                    expires_at=expires_at,
                )
            )
            await session.commit()
            await self._cache_session(refresh_token_hash, user_id)

            access_token = create_access_token(
                data={"user_id": user_id},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user_id": user_id,
            }

    async def login(
        self,
        username: str,
        password: str,
        device_id: Optional[str] = None,
        device_name: str = "Unknown",
        device_type: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> dict:
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(select(User).where(User.username == username))
            user = res.scalars().first()
            if not user or not verify_password(password, user.password_hash):
                raise ValueError("Неверный логин или пароль")
            if user.is_banned or not user.is_active:
                raise ValueError("Аккаунт заблокирован")

            user_id = int(user.id)
            is_new_device = False
            if device_id:
                existing_device = await session.execute(
                    select(Device.id).where(
                        Device.user_id == user_id,
                        Device.device_id == device_id,
                    )
                )
                is_new_device = existing_device.first() is None
            await self._upsert_device(session, user_id, device_id, device_name, device_type)

            refresh_token = secrets.token_urlsafe(32)
            refresh_token_hash = self._token_hash(refresh_token)
            expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
            session.add(
                SessionModel(
                    user_id=user_id,
                    refresh_token_hash=refresh_token_hash,
                    device_id=device_id,
                    device_info=device_name,
                    ip_address=ip_address,
                    expires_at=expires_at,
                )
            )
            await session.commit()
            await self._cache_session(refresh_token_hash, user_id)
            if is_new_device:
                await audit_log_service.log_security_event(
                    event_type="new_device_login",
                    user_id=user_id,
                    severity="warning",
                    details=f"Новое устройство: {device_name}",
                    ip_address=ip_address,
                    user_agent=device_name,
                )

            access_token = create_access_token(
                data={"user_id": user_id},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user_id": user_id,
            }

    async def refresh(self, refresh_token: str) -> dict:
        return await self.sessions_service.refresh(refresh_token)

    async def logout(self, refresh_token: str) -> bool:
        return await self.sessions_service.logout(refresh_token)

    async def get_sessions(self, user_id: int) -> list[SessionModel]:
        return await self.sessions_service.list_active(user_id)

    async def revoke_session(self, user_id: int, session_id: int) -> bool:
        return await self.sessions_service.revoke_one(user_id, session_id)

    async def revoke_all_except(self, user_id: int, current_refresh_token: str) -> int:
        return await self.sessions_service.revoke_all_except(
            user_id, current_refresh_token
        )

    async def get_me(self, user_id: int) -> User:
        return await self.profile_service.get_me(user_id)

    async def update_me(self, user_id: int, payload: dict) -> User:
        return await self.profile_service.update_me(user_id, payload)

    async def upsert_device_public_key(
        self,
        user_id: int,
        device_id: str,
        public_key: str,
        algorithm: str,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
    ) -> Device:
        return await self.device_keys_service.upsert_device_key(
            user_id=user_id,
            device_id=device_id,
            public_key=public_key,
            algorithm=algorithm,
            device_name=device_name,
            device_type=device_type,
            upsert_device_cb=self._upsert_device,
        )

    async def get_peer_device_keys(self, viewer_id: int, peer_user_id: int) -> list[Device]:
        return await self.device_keys_service.get_peer_keys(viewer_id, peer_user_id)

    async def get_direct_e2e_readiness(self, viewer_id: int, peer_user_id: int) -> dict:
        """
        Серверная проверка готовности E2E для direct-чата.

        Используется для подтверждения readiness на backend, а не на клиенте.
        """
        return await self.device_keys_service.get_direct_e2e_readiness(
            viewer_id, peer_user_id
        )

    # Обратная совместимость: старый single-key endpoint.
    async def upsert_public_key(self, user_id: int, public_key: str, algorithm: str = "p256-ecdh-v1") -> UserPublicKey:
        async with AsyncSession(db_engine.engine) as session:
            result = await session.execute(select(UserPublicKey).where(UserPublicKey.user_id == user_id))
            item = result.scalars().first()
            if not item:
                item = UserPublicKey(user_id=user_id, public_key=public_key, algorithm=algorithm)
            else:
                item.public_key = public_key
                item.algorithm = algorithm
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def get_public_key(self, user_id: int) -> UserPublicKey:
        async with AsyncSession(db_engine.engine) as session:
            device_res = await session.execute(
                select(Device)
                .where(Device.user_id == user_id, Device.public_key.is_not(None))
                .order_by(Device.key_updated_at.desc())
            )
            latest_device = device_res.scalars().first()
            if latest_device and latest_device.public_key:
                return UserPublicKey(
                    user_id=user_id,
                    public_key=latest_device.public_key,
                    algorithm=latest_device.key_algorithm,
                )
            result = await session.execute(select(UserPublicKey).where(UserPublicKey.user_id == user_id))
            user_public_key = result.scalars().first()
            if not user_public_key:
                raise ValueError("Публичный ключ E2E не найден")
            return user_public_key

    async def list_users_admin(self, actor_user_id: int) -> list[User]:
        await self._require_permission(actor_user_id, Permission.MANAGE_USERS)
        return await self.admin_service.list_users()

    async def set_admin(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        await self._require_super_admin(actor_user_id)
        return await self.admin_service.set_admin_flag(target_user_id, value)

    async def set_ban(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        await self._require_permission(actor_user_id, Permission.BAN_USERS)
        return await self.admin_service.set_ban_flag(target_user_id, value)

    async def set_active(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        await self._require_permission(actor_user_id, Permission.MANAGE_USERS)
        return await self.admin_service.set_active_flag(target_user_id, value)

    async def get_admin_overview(self, actor_user_id: int) -> dict:
        await self._require_permission(actor_user_id, Permission.VIEW_AUDIT_LOGS)
        return await self.admin_service.get_overview()

    async def set_role(self, actor_user_id: int, target_user_id: int, role: UserRole) -> User:
        await self._require_super_admin(actor_user_id)
        return await self.admin_service.set_role(target_user_id, role)

    async def grant_permission(self, actor_user_id: int, target_user_id: int, permission: str) -> None:
        await self._require_super_admin(actor_user_id)
        await self.admin_service.grant_permission(target_user_id, permission)

    async def revoke_permission(self, actor_user_id: int, target_user_id: int, permission: str) -> None:
        await self._require_super_admin(actor_user_id)
        await self.admin_service.revoke_permission(target_user_id, permission)

    async def set_user_profile_tag(self, actor_user_id: int, target_user_id: int, profile_tag: str | None) -> User:
        await self._require_permission(actor_user_id, Permission.MANAGE_USERS)
        return await self.admin_service.set_profile_tag(target_user_id, profile_tag)

    async def delete_user_account(self, actor_user_id: int, target_user_id: int) -> None:
        await self._require_permission(actor_user_id, Permission.MANAGE_USERS)
        if int(actor_user_id) == int(target_user_id):
            raise ValueError("Нельзя удалить собственный аккаунт через админ-панель")
        await self.admin_service.delete_user_account(target_user_id)

    async def get_effective_permissions(self, actor_user_id: int) -> set[str]:
        return await self.admin_service.get_user_effective_permissions(actor_user_id)

    async def _require_permission(self, actor_user_id: int, permission: str) -> None:
        actor = await self.get_me(actor_user_id)
        role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        extra = await self.admin_service.get_user_extra_permissions(actor_user_id)
        if not has_permission(role, permission, extra):
            raise ValueError("Недостаточно прав")

    async def ensure_permission(self, actor_user_id: int, permission: str) -> None:
        await self._require_permission(actor_user_id, permission)

    async def _require_super_admin(self, actor_user_id: int) -> None:
        actor = await self.get_me(actor_user_id)
        if actor.role != UserRole.SUPER_ADMIN:
            raise ValueError("Только SUPER_ADMIN может управлять ролями и правами")


auth_service = AuthService()
