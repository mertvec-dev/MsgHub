"""Use-case слой для профиля текущего пользователя."""

from datetime import datetime

from sqlmodel import select

from database.engine import db_engine
from database.models.users import User


class ProfileService:
    """Операции чтения и обновления профиля пользователя."""

    async def get_me(self, user_id: int) -> User:
        """Возвращает профиль текущего пользователя."""
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User).where(User.id == user_id))
            user = res.scalars().first()
            if not user:
                raise ValueError("Пользователь не найден")
            return user

    async def update_me(self, user_id: int, payload: dict) -> User:
        """Обновляет разрешенные поля профиля."""
        async for session in db_engine.get_async_session():
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

