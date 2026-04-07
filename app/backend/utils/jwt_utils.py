"""
JWT утилиты — создание, проверка, получение пользователя

JWT (JSON Web Token):
  - Состоит из 3 частей: header.payload.signature
  - Подписан SECRET_KEY — сервер может проверить подлинность
  - Access-token живёт 30 минут, refresh-токен — 7 дней (хранится в БД)
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from datetime import datetime, timezone, timedelta

from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.backend.config import settings


# ============================================================================
# СОЗДАНИЕ ТОКЕНОВ
# ============================================================================

def create_access_token(data: dict, expires_delta: timedelta) -> str:
    """
    Создаёт access-token (JWT).

    data — полезная нагрузка (обычно {"user_id": 123})
    expires_delta — сколько токен будет жить (timedelta)

    Формат payload:
    
    {
      "user_id": 123,
      "exp": 2026-04-04T15:30:00Z  # время истечения (UTC)
    }
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    payload.update({"exp": expire})

    # Подписываем payload секретным ключом
    token = jwt.encode(
        payload,
        key=settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,  # HS256
    )
    return token

def verify_token(token: str) -> dict | None:
    """
    Проверяет JWT-токен.

    Возвращает payload если токен валиден.
    Возвращает None если:
    - Токен просрочен (ExpiredSignatureError).
    - Подпись не совпадает (JWTError).
    """
    try:
        payload = jwt.decode(
            token,
            key=settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except (ExpiredSignatureError, JWTError):
        return None


# ============================================================================
# ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ ИЗ ТОКЕНА
# ============================================================================

# Готовый парсер — автоматически извлекает токен из заголовка:
#   Authorization: Bearer eyJhbGciOi...
security = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int:
    """
    FastAPI-зависимость — извлекает user_id из JWT-токена.

    **Как работает:**
    1. FastAPI автоматически парсит заголовок Authorization через HTTPBearer.
    2. credentials.credentials — это сам токен (строка после "Bearer ").
    3. verify_token проверяет подпись и срок.
    4. Возвращает user_id из payload.

    **Использование:**
    
    ```
    @router.get("/me")
    async def get_me(user_id: int = Depends(get_current_user)):
        # user_id уже проверен и валиден
        ...
    ```

    **Ошибки:**
    - 401 Unauthorized — токен невалиден, просрочен, или нет user_id.
    """
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен отсутствует",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен невалиден или истек",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_uid = payload.get("user_id")

    if raw_uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен не содержит user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return int(raw_uid)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен содержит некорректный user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )
