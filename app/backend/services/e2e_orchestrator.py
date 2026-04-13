"""
Оркестратор E2E readiness для direct-чатов.

Сервер публикует подтвержденные состояния в realtime, чтобы фронт не полагался
на локальные догадки.
"""

from app.backend.services.auth_service import auth_service
from app.backend.services.realtime_bus import realtime_bus


class E2EOrchestrator:
    async def sync_direct_pair(self, user_a: int, user_b: int, reason: str) -> None:
        """
        Публикует подтвержденное backend-состояние E2E readiness для обеих сторон.
        """
        for viewer_id, peer_id in ((user_a, user_b), (user_b, user_a)):
            try:
                readiness = await auth_service.get_direct_e2e_readiness(viewer_id, peer_id)
                await realtime_bus.emit_personal_event(
                    user_id=viewer_id,
                    payload={
                        "action": "direct_e2e_state",
                        "reason": reason,
                        "peer_id": peer_id,
                        "direct_room_id": readiness.get("direct_room_id"),
                        "ready": readiness.get("ready", False),
                        "e2e_reason": readiness.get("reason"),
                    },
                )
            except Exception:
                await realtime_bus.emit_personal_event(
                    user_id=viewer_id,
                    payload={
                        "action": "direct_e2e_state",
                        "reason": reason,
                        "peer_id": peer_id,
                        "ready": False,
                        "e2e_reason": "readiness_check_failed",
                    },
                )


e2e_orchestrator = E2EOrchestrator()
