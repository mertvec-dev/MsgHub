"""
Redis-подключение — асинхронный клиент

Используется для:
  1. Pub/Sub — синхронизация WebSocket между серверами
  2. Кэширование сессий — быстрый доступ к refresh-токенам
  3. Трекинг онлайна — кто на каком сервере сидит
  4. Rate limiting — счётчик запросов по IP
"""

import redis.asyncio as aioredis

from app.backend.config import settings


# Асинхронный Redis-клиент
# decode_responses=True — автоматически декодирует байты в строки
redis_client = aioredis.from_url(
    settings.REDIS_URL,  # redis://redis:6379/0
    encoding="utf-8",
    decode_responses=True,
)
