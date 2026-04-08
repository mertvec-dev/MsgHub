import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.backend.config import settings
from app.backend.utils.jwt_utils import create_access_token
from app.backend.utils.password_validator import hash_password, validate_password, verify_password
from database.engine import db_engine
from database.models.devices import Device
from database.models.friendships import Friendship, FriendshipStatus
from database.models.room_member import RoomMember
from database.models.sessions import Session as SessionModel
from database.models.users import User
from database.models.users_public_key import UserPublicKey
from database.redis import redis_client

logger = logging.getLogger(__name__)


class AuthService:
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
            for condition, msg in (
                (User.nickname == nickname, "Nickname уже занят"),
                (User.username == username, "Username уже занят"),
            ):
                res = await session.execute(select(User).where(condition))
                if res.scalars().first():
                    raise ValueError(msg)

            user = User(nickname=nickname, username=username, password_hash=hash_password(password))
            session.add(user)
            await session.flush()
            user_id = int(user.id)

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
        token_hash = self._token_hash(refresh_token)
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(
                    SessionModel.refresh_token_hash == token_hash,
                    SessionModel.expires_at > datetime.utcnow(),
                )
            )
            db_session = res.scalars().first()
            if not db_session:
                raise ValueError("Сессия недействительна")

            user_id = int(db_session.user_id)
            old_device_id = db_session.device_id
            old_device_info = db_session.device_info
            old_ip = db_session.ip_address
            await session.delete(db_session)

            new_refresh = secrets.token_urlsafe(32)
            new_hash = self._token_hash(new_refresh)
            session.add(
                SessionModel(
                    user_id=user_id,
                    refresh_token_hash=new_hash,
                    device_id=old_device_id,
                    device_info=old_device_info,
                    ip_address=old_ip,
                    expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                )
            )
            await session.commit()
            await self._cache_session(new_hash, user_id)
            try:
                await redis_client.delete(f"session:{token_hash}")
            except Exception:
                pass

            access_token = create_access_token(
                data={"user_id": user_id},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )
            return {
                "access_token": access_token,
                "refresh_token": new_refresh,
                "token_type": "bearer",
                "user_id": user_id,
            }

    async def logout(self, refresh_token: str) -> bool:
        token_hash = self._token_hash(refresh_token)
        try:
            await redis_client.delete(f"session:{token_hash}")
        except Exception:
            pass

        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
            )
            db_session = res.scalars().first()
            if not db_session:
                return False
            await session.delete(db_session)
            await session.commit()
            return True

    async def get_sessions(self, user_id: int) -> list[SessionModel]:
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel)
                .where(
                    SessionModel.user_id == user_id,
                    SessionModel.expires_at > datetime.utcnow(),
                )
                .order_by(SessionModel.last_active_at.desc())
            )
            return list(res.scalars().all())

    async def revoke_session(self, user_id: int, session_id: int) -> bool:
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(
                    SessionModel.id == session_id,
                    SessionModel.user_id == user_id,
                )
            )
            item = res.scalars().first()
            if not item:
                return False
            await redis_client.delete(f"session:{item.refresh_token_hash}")
            await session.delete(item)
            await session.commit()
            return True

    async def revoke_all_except(self, user_id: int, current_refresh_token: str) -> int:
        keep_hash = self._token_hash(current_refresh_token)
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id,
                    SessionModel.refresh_token_hash != keep_hash,
                )
            )
            items = list(res.scalars().all())
            for item in items:
                try:
                    await redis_client.delete(f"session:{item.refresh_token_hash}")
                except Exception:
                    pass
                await session.delete(item)
            await session.commit()
            return len(items)

    async def get_me(self, user_id: int) -> User:
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(select(User).where(User.id == user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            return user

    async def update_me(self, user_id: int, payload: dict) -> User:
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(select(User).where(User.id == user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            for key in ("nickname", "email", "avatar_url", "status_message", "profile_tag"):
                if key in payload and payload[key] is not None:
                    setattr(user, key, payload[key])
            user.updated_at = datetime.utcnow()
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def upsert_device_public_key(
        self,
        user_id: int,
        device_id: str,
        public_key: str,
        algorithm: str,
        device_name: Optional[str] = None,
        device_type: Optional[str] = None,
    ) -> Device:
        async with AsyncSession(db_engine.engine) as session:
            device = await self._upsert_device(session, user_id, device_id, device_name, device_type)
            if device is None:
                raise ValueError("device_id обязателен")
            device.public_key = public_key
            device.key_algorithm = algorithm
            device.key_updated_at = datetime.utcnow()
            session.add(device)
            await session.commit()
            await session.refresh(device)
            return device

    async def get_peer_device_keys(self, viewer_id: int, peer_user_id: int) -> list[Device]:
        async with AsyncSession(db_engine.engine) as session:
            friend_res = await session.execute(
                select(Friendship).where(
                    Friendship.status == FriendshipStatus.ACCEPTED,
                    (
                        ((Friendship.sender_id == viewer_id) & (Friendship.receiver_id == peer_user_id))
                        | ((Friendship.sender_id == peer_user_id) & (Friendship.receiver_id == viewer_id))
                    ),
                )
            )
            if not friend_res.scalars().first() and viewer_id != peer_user_id:
                shared_room = await session.execute(
                    select(RoomMember).where(RoomMember.user_id == viewer_id)
                )
                my_rooms = {r.room_id for r in shared_room.scalars().all()}
                peer_room = await session.execute(select(RoomMember).where(RoomMember.user_id == peer_user_id))
                peer_rooms = {r.room_id for r in peer_room.scalars().all()}
                if not (my_rooms & peer_rooms):
                    raise ValueError("Недостаточно прав для просмотра ключей устройства")

            res = await session.execute(
                select(Device).where(
                    Device.user_id == peer_user_id,
                    Device.public_key.is_not(None),
                )
            )
            return list(res.scalars().all())

    # Legacy compatibility.
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
        actor = await self.get_me(actor_user_id)
        if not actor.is_admin:
            raise ValueError("Недостаточно прав")
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(select(User).order_by(User.id.asc()))
            return list(res.scalars().all())

    async def set_admin(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        actor = await self.get_me(actor_user_id)
        if not actor.is_admin:
            raise ValueError("Недостаточно прав")
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(select(User).where(User.id == target_user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            user.is_admin = value
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def set_ban(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        actor = await self.get_me(actor_user_id)
        if not actor.is_admin:
            raise ValueError("Недостаточно прав")
        async with AsyncSession(db_engine.engine) as session:
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

    async def set_active(self, actor_user_id: int, target_user_id: int, value: bool) -> User:
        actor = await self.get_me(actor_user_id)
        if not actor.is_admin:
            raise ValueError("Недостаточно прав")
        async with AsyncSession(db_engine.engine) as session:
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


auth_service = AuthService()
