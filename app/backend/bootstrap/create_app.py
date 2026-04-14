"""Фабрика FastAPI-приложения."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.backend.bootstrap.exception_handlers import register_exception_handlers
from app.backend.bootstrap.lifespan import app_lifespan
from app.backend.bootstrap.ws_handler import websocket_endpoint
from app.backend.config import settings
from app.backend.routers import auth, friends, messages, rooms
from app.backend.utils.rate_limiter import limiter


def create_app() -> FastAPI:
    """Создает и конфигурирует приложение MsgHub API."""
    app = FastAPI(title="MsgHub API", version="1.0.0", lifespan=app_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    register_exception_handlers(app)

    app.websocket("/ws")(websocket_endpoint)

    app.include_router(auth.router)
    app.include_router(friends.router)
    app.include_router(rooms.router)
    app.include_router(messages.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Проверка деплоя бэкенда (проксируется из nginx: GET /health)."""
        return {"status": "ok", "service": "msghub-backend", "revision": settings.MSGHUB_REVISION}

    @app.get("/")
    async def root() -> dict[str, str]:
        """Проверка работоспособности API."""
        return {"status": "ok", "message": "MsgHub API is running"}

    return app

