"""
Единая шина realtime-событий.

Инкапсулирует локальную WS-доставку и межинстансную публикацию через Redis.
"""

from typing import Any, Dict
from uuid import uuid4

from app.backend.websocket import manager
from app.backend.services import pubsub


class RealtimeBus:
    """Фасад для fan-out событий в realtime."""

    @staticmethod
    def _with_event_id(payload: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(payload)
        data.setdefault("event_id", str(uuid4()))
        return data

    async def emit_personal_event(self, user_id: int, payload: Dict[str, Any]) -> None:
        """
        Отправляет персональное событие:
        - локально на текущем инстансе;
        - в Redis для доставки на других инстансах.
        """
        event_payload = self._with_event_id(payload)
        await manager.send_personal_message(event_payload, user_id)
        await pubsub.publish_message(
            {
                "action": "personal_event",
                "target_user_id": user_id,
                "event": event_payload,
            }
        )

    async def emit_room_event(
        self,
        room_id: int,
        payload: Dict[str, Any],
        exclude_user_id: int | None = None,
    ) -> None:
        """
        Отправляет событие в комнату:
        - локальный broadcast;
        - публикация в Redis для других инстансов.
        """
        event_payload = self._with_event_id(payload)
        await manager.broadcast_to_room(event_payload, room_id, exclude_user_id=exclude_user_id)
        await pubsub.publish_message(event_payload)


realtime_bus = RealtimeBus()
