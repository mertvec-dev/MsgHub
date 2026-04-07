"""
Роутер аутентификации — регистрация, вход, сессии, выход
"""

# ИМПОРТЫ — стандартные библиотеки, сторонние, внутренние
from fastapi import APIRouter, HTTPException, status, Depends, Request, Response

# Pydantic-схемы для валидации запросов/ответов
from app.backend.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    SessionInfo,
    SessionListResponse,
    LogoutResponse,
)
from app.backend.schemas.e2e import (
    E2EKeyRequest,
    PublicKeyResponse,
)

# Сервис аутентификации — вся бизнес-логика тут
from app.backend.services.auth_service import auth_service

# Получение user_id из JWT-токена
from app.backend.utils.jwt_utils import get_current_user

# Настройки (лимиты rate limiting)
from app.backend.config import settings
from app.backend.utils.rate_limiter import limiter

# РОУТЕР
router = APIRouter(prefix="/auth", tags=["auth"])

# ЭНДПОИНТЫ


def _response_payload(tokens: dict) -> dict:
    """
    Возвращает ответ с токенами и user_id

    Функция-helper
    """
    return {
        "access_token": tokens["access_token"],
        "token_type": tokens.get("token_type", "bearer"),
        "user_id": tokens["user_id"],
    }


def _public_key_response(model) -> PublicKeyResponse:
    """
    Возвращает ответ с публичным ключом E2E

    Функция-helper
    """
    return PublicKeyResponse(
        user_id=model.user_id,
        algorithm=model.algorithm,
        public_key=model.public_key,
    )


def _set_auth_cookies(response: Response, tokens: dict) -> None:
    """
    Устанавливает access/refresh токены в HttpOnly cookies
    
    По сути это helper-функция для установки токенов в cookies (чтобы не писать это в каждом роутере)
    """
    access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        max_age=access_max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        max_age=refresh_max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )

@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Регистрация нового пользователя",
    description="Создаёт аккаунт и возвращает access-токен (refresh хранится в HttpOnly-cookie)"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def register(request: Request, response: Response, data: RegisterRequest):
    """
    Принимает nickname, username, password.
    Сервис проверяет уникальность, хэширует пароль, создаёт сессию и токены

    Rate limit: {settings.RATE_LIMIT_LOGIN} — защита от массовых регистраций
    """
    try:
        tokens = await auth_service.register(
            nickname=data.nickname,
            username=data.username,
            password=data.password,
        )
        _set_auth_cookies(response, tokens)
        return _response_payload(tokens)
    except ValueError as e:
        # 400 — пользователь уже существует или невалидные данные
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Вход в аккаунт",
    description="Проверяет пароль и возвращает access-токен (refresh хранится в HttpOnly-cookie)"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(request: Request, response: Response, data: LoginRequest):
    """
    Принимает username и password.
    Сохраняет IP и User-Agent для трекинга сессий.

    Rate limit: {settings.RATE_LIMIT_LOGIN} — защита от брутфорса.
    """
    try:
        # IP-адрес клиента для логирования сессии
        ip = request.client.host
        # User-Agent браузера — будет виден в списке сессий
        device = request.headers.get("User-Agent", "Unknown")

        tokens = await auth_service.login(
            username=data.username,
            password=data.password,
            device_info=device,
            ip_address=ip,
        )
        _set_auth_cookies(response, tokens)
        return _response_payload(tokens)
    except ValueError as e:
        # 401 — неверный логин или пароль
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление access-токена",
    description="Обновляет access-токен по refresh-токену из HttpOnly-cookie"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def refresh_tokens(request: Request, response: Response):
    """
    Проверяет валидность refresh-токена в БД.
    Если токен отозван (logout) или истёк — возвращает 403.
    """
    try:
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refresh токен отсутствует",
            )
        tokens = await auth_service.refresh(refresh_token=refresh_token)
        _set_auth_cookies(response, tokens)
        return _response_payload(tokens)
    except ValueError as e:
        # 403 — токен невалиден или отозван
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Выход из аккаунта",
    description="Отзывает refresh-токен, удаляя сессию из БД"
)
async def logout(request: Request, response: Response):
    """Удаляет сессию по refresh-токену. Access-токен ещё работает до истечения."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh токен отсутствует",
        )
    success = await auth_service.logout(refresh_token=refresh_token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при выходе"
        )
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return LogoutResponse(message="Успешный выход")


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="Список активных сессий",
    description="Все сессии текущего пользователя (устройства, IP, время)"
)
async def get_sessions(user_id: int = Depends(get_current_user)):
    """
    Возвращает все активные сессии пользователя.
    Нужно для того, чтобы юзер видел, с каких устройств он залогинен.
    """
    # Получаем ORM-объекты сессий из БД
    db_sessions = await auth_service.get_sessions(user_id)

    # Конвертируем каждый ORM-объект в Pydantic-схему (валидация + сериализация)
    sessions_list = [SessionInfo.model_validate(s) for s in db_sessions]

    return SessionListResponse(sessions=sessions_list)

@router.post(
    "/e2e/public-key",
    response_model=PublicKeyResponse,
    summary="Обновление публичного ключа E2E",
    description="Обновляет публичный ключ E2E для текущего пользователя"
)
async def upsert_public_key(data: E2EKeyRequest, user_id: int = Depends(get_current_user)):
    """
    Обновляет публичный ключ E2E для текущего пользователя.
    """
    try:
        public_key = await auth_service.upsert_public_key(
            user_id=user_id, 
            public_key=data.public_key, 
            algorithm=data.algorithm
        )
        return _public_key_response(public_key)
    except ValueError as e:
        # 400 — ошибка при обновлении публичного ключа
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get(
    "/e2e/public-key/{user_id}",
    response_model=PublicKeyResponse,
    summary="Получение публичного ключа E2E",
    description="Получает публичный ключ E2E для конкретного пользователя"
)
async def get_public_key(user_id: int):
    """
    Получает публичный ключ E2E для конкретного пользователя.
    """
    try:
        public_key = await auth_service.get_public_key(user_id=user_id)
        return _public_key_response(public_key)
    except ValueError as e:
        # 400 — ошибка при получении публичного ключа
        raise HTTPException(        
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )