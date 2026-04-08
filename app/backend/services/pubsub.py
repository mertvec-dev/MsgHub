"""
Redis Pub/Sub — синхронизация WebSocket-сообщений между инстансами

Зачем:
  Когда серверов несколько (масштабирование), пользователь на Сервере А
  не получит сообщение от пользователя на Сервере Б — они не знают друг
  о друге

  Redis Pub/Sub решает это:
  1. Все серверы подписываются на канал 'msghub_messages'
  2. Когда Сервер А получает сообщение — он публикует его в Redis
  3. ВСЕ серверы (включая Сервер Б) получают сообщение
  4. Каждый сервер пересылает сообщение своим локальным пользователям
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import json
import asyncio
import logging
import os

from database.redis import redis_client
from app.backend.websocket import manager

logger = logging.getLogger(__name__)

# Имя Redis-канала для обмена сообщениями
CHANNEL_NAME = "msghub_messages"


# ============================================================================
# СЛУШАТЕЛЬ (фоновый цикл)
# ============================================================================

async def start_pubsub_listener():
    """
    Подписывается на Redis-канал и слушает сообщения от других серверов.

    Запускается один раз при старте приложения (в main.py lifespan).

    Работает в бесконечном цикле — пока сервер запущен.
    """
    # 1. Создаём pubsub-объект
    pubsub = redis_client.pubsub()

    # 2. Подписываемся на канал
    await pubsub.subscribe(CHANNEL_NAME)
    logger.info(f"Подписались на Redis канал: {CHANNEL_NAME}")

    # 3. Бесконечный цикл — слушаем сообщения
    try:
        async for message in pubsub.listen():
            # Redis возвращает два типа сообщений:
            # - type='subscribe' — подтверждение подписки (игнорируем)
            # - type='message'   — реальное сообщение от другого сервера
            if message["type"] == "message":
                data = json.loads(message["data"])
                await handle_message_from_redis(data)
    except asyncio.CancelledError:
        # Сервер останавливается — корректно отписываемся
        logger.info("Pub/Sub слушатель остановлен")
        await pubsub.unsubscribe(CHANNEL_NAME)
        await pubsub.close()


# ============================================================================
# ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ
# ============================================================================

async def handle_message_from_redis(data: dict):
    """
    Обрабатывает сообщение, пришедшее из Redis (от другого сервера)

    ПРИМЕЧАНИЕ: Фильтрация по _server_id отключена для локальных сообщений.
    На одном сервере broadcast_to_room вызывается напрямую из роутера,
    а Redis используется ТОЛЬКО для межсерверной синхронизации.
    """
    # Фильтруем только если это реально чужой сервер
    # (на одном сервере роутер сам делает broadcast_to_room)
    msg_server = data.get("_server_id")
    if msg_server and msg_server == os.getenv("SERVER_ID", "server_1"):
        # Это наше же сообщение — не нужно дублировать
        return

    action = data.get("action")

    # ─── Новое сообщение в комнате ───
    if action == "new_message":
        room_id = data.get("room_id")
        exclude_user_id = data.get("exclude_user_id")

        await manager.broadcast_to_room(
            message=data,
            room_id=room_id,
            exclude_user_id=exclude_user_id,
        )
        logger.debug(f"Переслали сообщение в комнату {room_id}")

    # ─── Сообщение отредактировано ────
    elif action == "message_edited":
        room_id = data.get("room_id")

        await manager.broadcast_to_room(
            message=data,
            room_id=room_id,
        )
        logger.debug(f"Переслали редактирование в комнату {room_id}")

    elif action == "message_deleted":
        room_id = data.get("room_id")
        await manager.broadcast_to_room(message=data, room_id=room_id)
        logger.debug(f"Переслали удаление сообщения в комнату {room_id}")

    elif action == "messages_read":
        room_id = data.get("room_id")
        await manager.broadcast_to_room(message=data, room_id=room_id)
        logger.debug(f"Переслали прочтение в комнату {room_id}")

    # ─── Новая комната создана ───
    elif action == "new_room":
        room_id = data.get("room_id")
        # Уведомление персональное — обрабатывается на уровне роутера
        logger.debug(f"Уведомление о новой комнате {room_id}")

    elif action == "direct_room_ready":
        peer_id = data.get("peer_id")
        if peer_id is not None:
            await manager.send_personal_message(data, int(peer_id))

    # ─── Системное уведомление ───
    elif action == "system":
        await manager.broadcast(data)
        logger.debug(f"Переслали системное уведомление")


# ============================================================================
# ПУБЛИКАЦИЯ
# ============================================================================

async def publish_message(data: dict):
    """
    Публикует сообщение в Redis-канал

    Вызывается когда текущий сервер получает новое сообщение от пользователя
    Все остальные серверы услышат и перешлют своим пользователям

    Добавляем server_id чтобы не обрабатывать своё же сообщение
    """
    data["_server_id"] = os.getenv("SERVER_ID", "server_1")
    await redis_client.publish(CHANNEL_NAME, json.dumps(data))
