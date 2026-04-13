"""Use-case слой для управления пользовательскими сессиями."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlmodel import select

from app.backend.config import settings
from app.backend.utils.jwt_utils import create_access_token
from database.engine import db_engine
from database.models.sessions import Session as SessionModel
from database.redis import redis_client


class SessionsService:
    """Инкапсулирует операции refresh/logout/revoke для сессий."""

    @staticmethod
    def token_hash(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode()).hexdigest()

    async def cache_session(self, token_hash: str, user_id: int) -> None:
        try:
            await redis_client.set(
                f"session:{token_hash}",
                str(user_id),
                ex=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            )
        except Exception:
            # Redis-кэш является оптимизацией: fallback идет через PostgreSQL.
            pass

    async def refresh(self, refresh_token: str) -> dict:
        token_hash = self.token_hash(refresh_token)
        async for session in db_engine.get_async_session():
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
            new_hash = self.token_hash(new_refresh)
            session.add(
                SessionModel(
                    user_id=user_id,
                    refresh_token_hash=new_hash,
                    device_id=old_device_id,
                    device_info=old_device_info,
                    ip_address=old_ip,
                    expires_at=datetime.utcnow()
                    + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                )
            )
            await session.commit()
            await self.cache_session(new_hash, user_id)
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
        token_hash = self.token_hash(refresh_token)
        try:
            await redis_client.delete(f"session:{token_hash}")
        except Exception:
            pass

        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
            )
            db_session = res.scalars().first()
            if not db_session:
                return False
            await session.delete(db_session)
            await session.commit()
            return True

    async def list_active(self, user_id: int) -> list[SessionModel]:
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(SessionModel)
                .where(
                    SessionModel.user_id == user_id,
                    SessionModel.expires_at > datetime.utcnow(),
                )
                .order_by(SessionModel.last_active_at.desc())
            )
            return list(res.scalars().all())

    async def revoke_one(self, user_id: int, session_id: int) -> bool:
        async for session in db_engine.get_async_session():
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
        keep_hash = self.token_hash(current_refresh_token)
        async for session in db_engine.get_async_session():
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

