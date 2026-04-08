"""
Главный файл приложения — точка входа FastAPI

Что здесь происходит:
  1. Создаётся FastAPI-приложение с lifespan (startup/shutdown)
  2. Подключается CORS, Rate Limiting, Exception Handlers
  3. Регистрируется WebSocket-эндпоинт
  4. Подключаются роутеры (auth, friends, rooms, messages)
"""

# ============================================================================
# ИМПОРТЫ — стандартные библиотеки и FastAPI
# ============================================================================
import json
import logging
from contextlib import asynccontextmanager

# FastAPI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Pydantic — валидация
from pydantic import ValidationError

# Rate limiting — slowapi
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Асинхронность
import asyncio

# ============================================================================
# ИМПОРТЫ — внутренние модули
# ============================================================================

# База данных — инициализация и закрытие
from database.engine import db_engine

# Роутеры — эндпоинты API
from app.backend.routers import auth
from app.backend.routers import friends
from app.backend.routers import rooms
from app.backend.routers import messages

# WebSocket — менеджер подключений
from app.backend.websocket import manager

# Pub/Sub — слушатель Redis-канала
from app.backend.services import pubsub

# Конфиг — настройки приложения
from app.backend.config import settings

# Rate limiting — лимитер
from app.backend.utils.rate_limiter import limiter

# Валидация токена
from app.backend.utils.jwt_utils import verify_token


# ============================================================================
# ЛОГИРОВАНИЕ (написано нейросетью)
# ============================================================================

# Глобальная настройка logging для всего приложения
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),  # INFO / DEBUG / WARNING
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================================
# LIFESPAN — запуск и остановка приложения
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения.

    **Startup (при запуске):**
    1. Инициализирует БД (создаёт таблицы если нет).
    2. Запускает фоновый слушатель Redis Pub/Sub.

    **Shutdown (при остановке):**
    1. Закрывает подключения к БД.
    """
    # ─── STARTUP ───
    logger.info("Запуск MsgHub Backend...")

    # Создаём таблицы в БД 
    await db_engine.init_db()
    logger.info("База данных готова")

    # Запускаем слушатель Redis Pub/Sub в фоне
    # Он получает сообщения от других инстансов и пересылает юзерам
    try:
        asyncio.create_task(pubsub.start_pubsub_listener())
        logger.info("Pub/Sub слушатель запущен")
    except Exception as e:
        logger.error(f"Ошибка запуска Pub/Sub: {e}")

    yield  # Приложение работает здесь

    # ─── SHUTDOWN ───
    logger.info("Остановка сервера...")
    await db_engine.close_db()
    logger.info("БД отключена")


# ============================================================================
# ПРИЛОЖЕНИЕ
# ============================================================================

app = FastAPI(
    title="MsgHub API",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

# ─── CORS ───
# Разрешает запросы только с указанных origin (фронтенд)
# allow_credentials=True — разрешает отправку cookies и Authorization заголовков
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Из .env: http://localhost:5173
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Rate Limiting ───
# Подключаем slowapi — ограничение частоты запросов по IP
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ============================================================================
# WEBSOCKET
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket-эндпоинт для real-time сообщений

    **Протокол:**
    1. Клиент подключается: ws://localhost:8000/ws
    2. Клиент шлет первое сообщение: {"action": "auth", "token": "..."}
    3. Сервер проверяет токен и регистрирует юзера
    4. Далее обычный обмен (join_room, ping/pong)
    """
    # 1. Принимаем сырое соединение
    await websocket.accept()
    logger.info("WebSocket: сырое соединение принято, жду auth...")

    try:
        # 2. Ждем первое сообщение с токеном
        first_msg = await websocket.receive_text()
        data = json.loads(first_msg)

        if data.get("action") != "auth":
            logger.warning("WebSocket: первое сообщение должно быть auth")
            await websocket.close(code=4001)
            return

        token = data.get("token")
        if not token:
            await websocket.close(code=4001)
            return

        # 3. Проверяем токен
        payload = verify_token(token)
        if not payload:
            logger.warning("WebSocket: неверный токен")
            await websocket.close(code=4001)
            return

        user_id = payload.get("user_id")
        if not user_id:
            await websocket.close(code=4001)
            return

        # 4. Регистрируем в менеджере
        await manager.connect(websocket, user_id)
        logger.info(f"WebSocket подключился: user_id={user_id}")

        # Явный вызов: клиент после этого шлёт join_room (иначе гонка с порядком сообщений) (написано нейросетью)
        await websocket.send_json({"action": "authenticated", "user_id": user_id})

        # 5. Основной цикл обмена сообщениями
        while True:
            msg = await websocket.receive_text()
            message_data = json.loads(msg)

            if message_data.get("action") == "join_room":
                room_id = message_data.get("room_id")
                manager.set_user_room(user_id, room_id)
                logger.info(f"user_id={user_id} присоединился к room_id={room_id}")
                await manager.send_personal_message(
                    {"action": "joined_room", "room_id": room_id}, user_id
                )
            elif message_data.get("action") == "ping":
                await manager.send_personal_message({"action": "pong"}, user_id)

    except WebSocketDisconnect:
        if 'user_id' in locals():
            manager.disconnect_socket(user_id, websocket)
            logger.info(f"WebSocket отключился: user_id={user_id}")
    except Exception as e:
        logger.error(f"WebSocket ошибка: {e}")
        if 'user_id' in locals():
            manager.disconnect_socket(user_id, websocket)


# ============================================================================
# Обработчик исключений валидации Pydantic (написано нейросетью)
# ============================================================================

# Маппинг Pydantic-ошибок
_VALIDATION_MESSAGES_RU = {
    "string_too_short": "Поле слишком короткое",
    "string_too_long": "Поле слишком длинное",
    "string_pattern_mismatch": "Неверный формат поля",
    "missing": "Обязательное поле",
    "int_parsing": "Должно быть числом",
    "int_parsing_size": "Число слишком большое",
    "float_parsing": "Должно быть числом",
    "value_error.missing": "Обязательное поле",
    "min_length": "Минимум {min_length} символов",
    "max_length": "Максимум {max_length} символов",
    "less_than_equal": "Значение должно быть меньше или равно {le}",
    "greater_than_equal": "Значение должно быть больше или равно {ge}",
    "too_short": "Минимум {min_length} символов",
    "too_long": "Максимум {max_length} символов",
}


def _translate_pydantic_error(err: dict) -> str:
    """Переводит ошибку Pydantic на русский (написано нейросетью)"""
    error_type = err.get("type", "")
    msg = err.get("msg", "")

    # Если msg уже на русском (кастомная валидация) — оставляем
    if msg and not any(c in msg for c in "abcdefghijklmnopqrstuvwxyz"):
        return msg

    # Пробуем шаблонный перевод
    template = _VALIDATION_MESSAGES_RU.get(error_type)
    if template:
        # Подставляем параметры
        ctx = err.get("ctx", {})
        result = template
        for key, val in ctx.items():
            result = result.replace("{" + key + "}", str(val))
        return result

    # Fallback: убираем технический английский
    return msg or "Ошибка валидации"


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """
    Глобальный обработчик ошибок валидации Pydantic
    Переводит ошибки на русский язык
    (написано нейросетью)
    """
    translated = [
        {
            "loc": e.get("loc", []),
            "msg": _translate_pydantic_error(e),
            "type": e.get("type", "unknown"),
        }
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": translated},
    )


# ============================================================================
# РОУТЕРЫ
# ============================================================================

# Подключаем все эндпоинты API
app.include_router(auth.router)      # POST /auth/register, /auth/login, ...
app.include_router(friends.router)   # POST /friends/request, GET /friends/, ...
app.include_router(rooms.router)     # POST /rooms/create, GET /rooms/my, ...
app.include_router(messages.router)  # GET /messages/{room_id}, POST /messages/send, ...

# app.include_router(admin.router)   


# ============================================================================
# КОРНЕВОЙ ЭНДПОИНТ
# ============================================================================

@app.get("/")
async def root():
    """Проверка что сервер работает (healthcheck)"""
    return {"status": "ok", "message": "MsgHub API is running"}
