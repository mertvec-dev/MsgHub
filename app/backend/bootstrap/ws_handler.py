"""WebSocket endpoint и обработка сообщений протокола."""

import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.backend.utils.jwt_utils import verify_token
from app.backend.websocket import manager

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    Обрабатывает WebSocket-сессию клиента.

    Протокол:
    1) клиент отправляет `auth` с access token;
    2) после `authenticated` может отправлять `join_room` и `ping`.
    """
    await websocket.accept()
    logger.info("WebSocket: сырое соединение принято, жду auth...")

    user_id: Optional[int] = None
    try:
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

        payload = verify_token(token)
        if not payload:
            logger.warning("WebSocket: неверный токен")
            await websocket.close(code=4001)
            return

        user_id = payload.get("user_id")
        if not user_id:
            await websocket.close(code=4001)
            return

        await manager.connect(websocket, user_id)
        logger.info("WebSocket подключился: user_id=%s", user_id)
        await websocket.send_json({"action": "authenticated", "user_id": user_id})

        while True:
            msg = await websocket.receive_text()
            message_data = json.loads(msg)
            action = message_data.get("action")

            if action == "join_room":
                room_id = message_data.get("room_id")
                manager.set_user_room(user_id, room_id)
                logger.info("user_id=%s присоединился к room_id=%s", user_id, room_id)
                await manager.send_personal_message(
                    {"action": "joined_room", "room_id": room_id},
                    user_id,
                )
            elif action == "ping":
                await manager.send_personal_message({"action": "pong"}, user_id)

    except WebSocketDisconnect:
        if user_id is not None:
            manager.disconnect_socket(user_id, websocket)
            logger.info("WebSocket отключился: user_id=%s", user_id)
    except Exception as exc:
        logger.error("WebSocket ошибка: %s", exc)
        if user_id is not None:
            manager.disconnect_socket(user_id, websocket)

