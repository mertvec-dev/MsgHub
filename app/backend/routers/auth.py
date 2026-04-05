"""
Роутер аутентификации — регистрация, вход, сессии, выход
"""

# ИМПОРТЫ — стандартные библиотеки, сторонние, внутренние
from fastapi import APIRouter, HTTPException, status, Depends, Request

# Pydantic-схемы для валидации запросов/ответов
from app.backend.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    SessionInfo,
    SessionListResponse,
    LogoutResponse,
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

@router.post(
    "/register",
    response_model=TokenResponse,
    summary="Регистрация нового пользователя",
    description="Создаёт аккаунт и возвращает пару access + refresh токенов"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def register(request: Request, data: RegisterRequest):
    """
    Принимает nickname, username, password, email (опционально)
    Сервис проверяет уникальность, хэширует пароль, создаёт сессию и токены

    Rate limit: {settings.RATE_LIMIT_LOGIN} — защита от массовых регистраций
    """
    try:
        tokens = await auth_service.register(
            nickname=data.nickname,
            username=data.username,
            password=data.password,
            email=data.email,
        )
        return tokens
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
    description="Проверяет пароль и возвращает токены"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(request: Request, data: LoginRequest):
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
        return tokens
    except ValueError as e:
        # 401 — неверный логин или пароль
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновление токенов",
    description="Возвращает новую пару токенов по refresh-токену"
)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def refresh_tokens(request: Request, data: RefreshRequest):
    """
    Проверяет валидность refresh-токена в БД.
    Если токен отозван (logout) или истёк — возвращает 403.
    """
    try:
        tokens = await auth_service.refresh(refresh_token=data.refresh_token)
        return tokens
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
async def logout(data: RefreshRequest):
    """Удаляет сессию по refresh-токену. Access-токен ещё работает до истечения."""
    success = await auth_service.logout(refresh_token=data.refresh_token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка при выходе"
        )
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
