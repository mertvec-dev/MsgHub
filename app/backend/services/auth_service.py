"""
Сервис аутентификации — регистрация, логин, ротация токенов, сессии

Отвечает за:
  - Создание аккаунта с валидацией
  - Вход по логину/паролю
  - Выдачу пары access + refresh токенов
  - Ротацию refresh-токенов (refresh → новая пара)
  - Отзыв сессий (logout)
  - Трекинг активных сессий

Хранит сессии в PostgreSQL + Redis (для быстрого доступа)
"""

# ============================================================================
# ИМПОРТЫ — стандартные
# ============================================================================
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

# ============================================================================
# ИМПОРТЫ — БД и ORM
# ============================================================================
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import db_engine
from database.models.users import User
from database.models.users_public_key import UserPublicKey
from database.models.sessions import Session as SessionModel
from database.redis import redis_client

# ============================================================================
# ИМПОРТЫ — утилиты и конфиг
# ============================================================================
from app.backend.config import settings
from app.backend.utils.password_validator import validate_password, hash_password, verify_password
from app.backend.utils.jwt_utils import create_access_token

# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================
logger = logging.getLogger(__name__)

# Если логгер security ещё не настроен — настраиваем
if not logging.getLogger("security").handlers:
    security_logger = logging.getLogger("security")
    security_logger.setLevel(logging.WARNING)
    handler = logging.FileHandler("security.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    security_logger.addHandler(handler)


# ============================================================================
# СЕРВИС
# ============================================================================

class AuthService:
    """
    Управляет жизненным циклом аутентификации:
    register → login → refresh → logout
    """

    # ==========================================================================
    # РЕГИСТРАЦИЯ
    # ==========================================================================

    async def register(
        self,
        nickname: str,
        username: str,
        password: str,
    ) -> dict:
        """
        Создаёт нового пользователя и возвращает токены.

        Шаги:
        1. Валидация пароля (сложность).
        2. Проверка уникальности nickname/username.
        3. Создание записи User в БД.
        4. Создание сессии (refresh_token) в БД.
        5. Кэширование сессии в Redis (быстрая проверка при refresh).
        6. Генерация access_token (JWT).
        """
        # Проверяем сложность пароля (длина, спецсимволы и т.д.)
        if not validate_password(password):
            raise ValueError("Слабый пароль")

        async with AsyncSession(db_engine.engine) as session:
            # 1. Проверяем что nickname/username свободны
            checks = [
                (User.nickname == nickname, "Nickname уже занят"),
                (User.username == username, "Username уже занят"),
            ]

            for condition, error_msg in checks:
                res = await session.execute(select(User).where(condition))
                if res.scalars().first():
                    raise ValueError(error_msg)

            # 2. Создаём пользователя
            user = User(
                nickname=nickname,
                username=username,
                password_hash=hash_password(password),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            # Сохраняем ID сразу — после commit сессия может быть закрыта
            saved_user_id = user.id
            if not saved_user_id:
                raise ValueError("ID пользователя не получен после создания")

            # 3. Генерируем refresh-токен (случайная строка 64 символа)
            refresh_token = secrets.token_urlsafe(32)
            # Хэшируем токен
            refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

            # 4. Записываем сессию в БД
            db_session = SessionModel(
                user_id=saved_user_id,
                refresh_token_hash=refresh_token_hash,
                device_info="Auto-Login",
                ip_address="127.0.0.1",
                expires_at=expires_at,
            )
            session.add(db_session)
            await session.commit()

            # 5. Кэшируем в Redis — ключ: "session:{хэш}", значение: user_id
            # TTL = 7 дней (совпадает с REFRESH_TOKEN_EXPIRE_DAYS)
            try:
                await redis_client.set(
                    f"session:{refresh_token_hash}",
                    str(saved_user_id),
                    ex=604800,  # 7 дней в секундах
                )
            except Exception as e:
                # Redis упал — не критично, сессия всё ещё в БД
                logger.error(f"Redis Error при регистрации: {e}")

            # 6. Генерируем access_token (JWT, живёт 30 минут)
            access_token = create_access_token(
                data={"user_id": saved_user_id},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user_id": saved_user_id,
            }

    # ==========================================================================
    # ВХОД
    # ==========================================================================

    async def login(
        self,
        username: str,
        password: str,
        device_info: str = "Unknown",
        ip_address: str = "127.0.0.1",
    ) -> dict:
        """
        Проверяет логин/пароль и выдаёт токены.

        Шаги:
        1. Ищем пользователя по username.
        2. Сверяем хэш пароля.
        3. Создаём новую сессию (refresh_token) в БД.
        4. Кэшируем в Redis.
        5. Генерируем access_token.
        """
        async with AsyncSession(db_engine.engine) as session:
            # 1. Ищем пользователя
            res = await session.execute(select(User).where(User.username == username))
            user = res.scalars().first()

            # 2. Проверяем пароль (сравнение хэшей bcrypt)
            if not user or not verify_password(password, user.password_hash):
                raise ValueError("Неверный логин или пароль")

            saved_user_id = user.id

            # 3. Генерируем refresh-токен
            refresh_token = secrets.token_urlsafe(32)
            refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
            expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

            # 4. Записываем сессию в БД
            db_session = SessionModel(
                user_id=saved_user_id,
                refresh_token_hash=refresh_token_hash,
                device_info=device_info,
                ip_address=ip_address,
                expires_at=expires_at,
            )
            session.add(db_session)
            await session.commit()

            # 5. Кэш в Redis
            try:
                await redis_client.set(
                    f"session:{refresh_token_hash}",
                    str(saved_user_id),
                    ex=604800,
                )
            except Exception:
                pass  # Не критично

            # 6. Access-token
            access_token = create_access_token(
                data={"user_id": saved_user_id},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user_id": saved_user_id,
            }

    # ==========================================================================
    # РОТАЦИЯ ТОКЕНОВ
    # ==========================================================================

    async def refresh(self, refresh_token: str) -> dict:
        """
        Меняет пару токенов на новую (rotation).

        Шаги:
        1. Ищем хэш refresh-токена в Redis (быстро).
        2. Если нет — проверяем в БД.
        3. Удаляем старую сессию (rotation — одноразовый токен).
        4. Создаём новую сессию.
        5. Возвращаем новую пару токенов.

        **Зачем rotation:**
        Если кто-то украл refresh-токен, то после использования старый токен
        становится невалидным. Это позволяет обнаружить компрометацию
        """
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        redis_key = f"session:{token_hash}"

        async with AsyncSession(db_engine.engine) as session:
            # 1) Сначала пытаемся быстрый путь через Redis.
            # Если Redis недоступен/пустой — fallback на БД (сессия может быть валидна).
            user_id = None
            try:
                user_id = await redis_client.get(redis_key)
            except Exception:
                user_id = None

            # 2) Проверяем в БД — источник истины по refresh-сессиям.
            res = await session.execute(
                select(SessionModel).where(
                    SessionModel.refresh_token_hash == token_hash,
                    SessionModel.expires_at > datetime.utcnow(),
                )
            )
            db_session = res.scalars().first()

            if not db_session:
                # Сессия отозвана (logout) или истекла — чистим Redis
                try:
                    await redis_client.delete(redis_key)
                except Exception:
                    pass
                raise ValueError("Сессия недействительна")

            # Если Redis промахнулся, но БД валидна — используем user_id из БД.
            if not user_id:
                user_id = db_session.user_id

            # 3. Удаляем старую сессию (rotation — токен одноразовый)
            await session.delete(db_session)

            # 4. Создаём новую
            new_refresh_token = secrets.token_urlsafe(32)
            new_token_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()
            new_expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

            new_session = SessionModel(
                user_id=int(user_id),
                refresh_token_hash=new_token_hash,
                device_info=db_session.device_info,
                ip_address=db_session.ip_address,
                expires_at=new_expires_at,
            )
            session.add(new_session)
            await session.commit()

            # 5. Обновляем кэш Redis
            try:
                await redis_client.set(
                    f"session:{new_token_hash}",
                    str(int(user_id)),
                    ex=604800,
                )
            except Exception:
                pass

            # 6. Новый access-token
            new_access_token = create_access_token(
                data={"user_id": int(user_id)},
                expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            )

            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "user_id": int(user_id),
            }

    # ==========================================================================
    # ВЫХОД
    # ==========================================================================

    async def logout(self, refresh_token: str) -> bool:
        """
        Отзывает refresh-токен — удаляет из Redis и БД.

        Access-token ещё работает до истечения (30 мин), но refresh уже нельзя
        использовать для получения нового.
        """
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        # Удаляем из Redis
        try:
            await redis_client.delete(f"session:{token_hash}")
        except Exception:
            pass

        # Удаляем из БД
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(SessionModel.refresh_token_hash == token_hash)
            )
            db_session = res.scalars().first()
            if db_session:
                await session.delete(db_session)
                await session.commit()
                return True
        return False

    # ==========================================================================
    # СЕССИИ
    # ==========================================================================

    async def get_sessions(self, user_id: int) -> list:
        """
        Возвращает все активные сессии пользователя.
        Сортировка: последние активные — сверху.
        """
        async with AsyncSession(db_engine.engine) as session:
            res = await session.execute(
                select(SessionModel).where(
                    SessionModel.user_id == user_id,
                    SessionModel.expires_at > datetime.utcnow(),
                ).order_by(SessionModel.last_active_at.desc())
            )
            return res.scalars().all()
    
    # ==========================================================================
    # ПОЛУЧЕНИЕ КЛЮЧА ДЛЯ ШИФРОВАНИЯ
    # ==========================================================================
    async def upsert_public_key(self, user_id: int, public_key: str, algorithm: str = "x25519") -> UserPublicKey:
        """
        Обновляет публичный ключ E2E для текущего пользователя, или создает новый, если не существует
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(UserPublicKey).where(UserPublicKey.user_id == user_id)
            )
            user_public_key = result.scalars().first()

            if not user_public_key: # если ключ не существует, создаем новый
                user_public_key = UserPublicKey( # создаем новый ключ
                    user_id=user_id,
                    public_key=public_key,
                    algorithm=algorithm,
                )
            else:
                user_public_key.public_key = public_key
                user_public_key.algorithm = algorithm

            # добавляем ключ в БД
            session.add(user_public_key) # транзакция сразу добавляет ключ в БД
            await session.commit() # коммитим транзакцию
            await session.refresh(user_public_key) # обновляем объект ключа
            return user_public_key
    
    async def get_public_key(self, user_id: int) -> UserPublicKey:
        """
        Получает публичный ключ E2E для конкретного пользователя
        """
        async for session in db_engine.get_async_session():
            result = await session.execute(
                select(UserPublicKey).where(UserPublicKey.user_id == user_id)
            )
            user_public_key = result.scalars().first()
            if not user_public_key:
                raise ValueError("Публичный ключ E2E не найден")
            return user_public_key

# Глобальный экземпляр — используется в роутерах
auth_service = AuthService()
