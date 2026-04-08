"""
WebSocket Connection Manager
Управляет всеми активными WebSocket-подключениями

Отвечает за:
  - Приём новых подключений (connect)
  - Отключение (disconnect)
  - Отправку сообщений конкретному пользователю (send_personal_message)
  - Рассылку всем пользователям в комнате (broadcast_to_room)
  - Отслеживание: кто онлайн, в какой комнате находится

Архитектура:
  Хранит подключения в памяти сервера (словари)
  Дополнительно дублирует в Redis (для масштабирования на несколько серверов)
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import os
import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

from database.redis import redis_client

logger = logging.getLogger(__name__)


# ============================================================================
# МЕНЕДЖЕР ПОДКЛЮЧЕНИЙ
# ============================================================================

class ConnectionManager:
    """
    Управляет WebSocket-подключениями и отслеживает комнаты пользователей

    **Структуры данных:**
    - active_connections: {user_id: WebSocket} — активные соединения
    - user_rooms: {user_id: room_id} — в какой комнате сидит пользователь

    **Redis-ключи:**
    - msghub:online:{user_id} = "server_id" — на каком сервере пользователь
    - msghub:room:{room_id} = {user_id: server_id, ...} — кто в комнате
    """

    def __init__(self):
        # Активные WebSocket-соединения на ЭТОМ сервере (multi-device)
        self.active_connections: dict[int, list[WebSocket]] = {}

        # Комнаты пользователей на ЭТОМ сервере
        self.user_rooms: dict[int, int] = {}

        # Префиксы для Redis-ключей
        self.ONLINE_PREFIX = "msghub:online:"
        self.ROOM_PREFIX = "msghub:room:"

        # ID текущего сервера (для масштабирования)
        # Если запущен один сервер — всегда "server_1"
        self.server_id = os.getenv("SERVER_ID", "server_1")

    # ==========================================================================
    # ПОДКЛЮЧЕНИЕ / ОТКЛЮЧЕНИЕ
    # ==========================================================================

    async def connect(self, websocket: WebSocket, user_id: int):
        """
        Регистрирует уже принятое WebSocket-соединение (accept вызывает endpoint в main.py).

        Шаги:
        1. Сохраняет в локальный словарь.
        2. Записывает в Redis — «юзер онлайн на этом сервере».
        """
        sockets = self.active_connections.setdefault(user_id, [])
        sockets.append(websocket)

        # Регистрируем онлайн-статус в Redis (TTL 60 сек — обновляется при reconnect)
        await redis_client.set(
            f"{self.ONLINE_PREFIX}{user_id}",
            self.server_id,
            ex=60,
        )

    def disconnect(self, user_id: int):
        """
        Отключает пользователя и удаляет из словарей.

        Redis-записи удаляются асинхронно (через create_task),
        чтобы не блокировать основной поток.
        """
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_rooms:
            del self.user_rooms[user_id]

        # Асинхронно удаляем из Redis
        asyncio.create_task(self._remove_from_redis(user_id))

    def disconnect_socket(self, user_id: int, websocket: WebSocket):
        """Удаляет конкретный сокет пользователя, не трогая остальные устройства."""
        sockets = self.active_connections.get(user_id)
        if not sockets:
            return
        self.active_connections[user_id] = [ws for ws in sockets if ws is not websocket]
        if not self.active_connections[user_id]:
            self.disconnect(user_id)

    async def _remove_from_redis(self, user_id: int):
        """Удаляет пользователя из Redis-ключей онлайна и комнат."""
        try:
            await redis_client.delete(f"{self.ONLINE_PREFIX}{user_id}")
            await redis_client.hdel(f"{self.ROOM_PREFIX}all", str(user_id))
        except Exception as e:
            logger.error(f"Ошибка удаления из Redis: {e}")

    # ==========================================================================
    # УПРАВЛЕНИЕ КОМНАТАМИ
    # ==========================================================================

    def set_user_room(self, user_id: int, room_id: int):
        """
        Запоминает, в какую комнату зашёл пользователь.

        Нужно для broadcast_to_room — чтобы знать кому слать.
        """
        self.user_rooms[user_id] = room_id

        # Асинхронно сохраняем в Redis (для других серверов)
        # Создаем фоновую задачу для главного цикла событий, говоря ему, что тут нужно выполнить задачу
        # Не блокируя основной код
        asyncio.create_task(self._save_room_to_redis(user_id, room_id))

    async def _save_room_to_redis(self, user_id: int, room_id: int):
        """Сохраняет комнату пользователя в Redis."""
        try:
            await redis_client.hset(
                f"{self.ROOM_PREFIX}{room_id}",
                str(user_id),
                self.server_id,
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения комнаты в Redis: {e}")

    def get_user_room(self, user_id: int) -> Optional[int]:
        """Возвращает комнату пользователя (или None)."""
        return self.user_rooms.get(user_id)

    # ==========================================================================
    # ОТПРАВКА СООБЩЕНИЙ
    # ==========================================================================

    async def send_personal_message(self, message: dict, user_id: int):
        """
        Отправляет JSON-сообщение одному пользователю.

        Если пользователь отключился — автоматически убирает из менеджера.
        """
        sockets = self.active_connections.get(user_id, [])
        disconnected = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)
        for ws in disconnected:
            self.disconnect_socket(user_id, ws)

    async def broadcast_to_room(
        self,
        message: dict,
        room_id: int,
        exclude_user_id: Optional[int] = None,
    ):
        """
        Рассылает сообщение всем пользователям в комнате (на этом сервере).

        exclude_user_id — не отправлять этому пользователю (обычно отправителю).
        """
        for uid, connected_room_id in list(self.user_rooms.items()):
            if connected_room_id == room_id:
                if exclude_user_id and uid == exclude_user_id:
                    continue

                if uid in self.active_connections:
                    sockets = list(self.active_connections[uid])
                    for websocket in sockets:
                        try:
                            await websocket.send_json(message)
                        except Exception:
                            self.disconnect_socket(uid, websocket)

        # Очистка выполняется точечно через disconnect_socket в цикле отправки.

    async def broadcast(self, message: dict):
        """
        Рассылает сообщение ВСЕМ подключённым пользователям.

        Используется для системных уведомлений.
        """
        for uid, sockets in list(self.active_connections.items()):
            for websocket in list(sockets):
                try:
                    await websocket.send_json(message)
                except Exception:
                    self.disconnect_socket(uid, websocket)

    # ==========================================================================
    # ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЯХ
    # ==========================================================================

    def get_online_users(self) -> list[int]:
        """Возвращает список онлайн-пользователей на ЭТОМ сервере."""
        return list(self.active_connections.keys())

    async def get_online_users_count(self, room_id: int) -> int:
        """
        Возвращает количество пользователей в комнате (включая другие серверы).
        """
        try:
            return await redis_client.hlen(f"{self.ROOM_PREFIX}{room_id}")
        except Exception:
            return len(self.get_users_in_room(room_id))

    def get_users_in_room(self, room_id: int) -> list[int]:
        """Возвращает пользователей в комнате (на ЭТОМ сервере)."""
        return [uid for uid, rid in self.user_rooms.items() if rid == room_id]

    def is_online(self, user_id: int) -> bool:
        """Проверяет, онлайн ли пользователь (на ЭТОМ сервере)."""
        return bool(self.active_connections.get(user_id))

    async def is_online_global(self, user_id: int) -> bool:
        """
        Проверяет, онлайн ли пользователь (на ЛЮБОМ сервере через Redis).
        """
        try:
            return await redis_client.exists(f"{self.ONLINE_PREFIX}{user_id}") > 0
        except Exception:
            return self.is_online(user_id)


# Глобальный экземпляр — используется в роутерах и main.py
manager = ConnectionManager()
