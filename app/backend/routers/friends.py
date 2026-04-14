"""
Роутер друзей — заявки, принятие, отклонение, список друзей
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from fastapi import APIRouter, Depends, Request

import logging

from app.backend.schemas.friends import FriendRequest

# Сервис друзей — бизнес-логика
from app.backend.services.friends_service import friends_service
from app.backend.services.auth_service import auth_service
from app.backend.services.realtime_bus import realtime_bus
from app.backend.services.e2e_orchestrator import e2e_orchestrator
from app.backend.utils.rate_limiter import limiter
from app.backend.config import settings

# Получение user_id из JWT-токена
from app.backend.utils.jwt_utils import require_active_user

# WebSocket менеджер — для отображения онлайн-статуса
from app.backend.websocket import manager

logger = logging.getLogger(__name__)

# ============================================================================
# РОУТЕР
# ============================================================================

router = APIRouter(prefix="/friends", tags=["friends"])

# ============================================================================
# ЭНДПОИНТЫ
# ============================================================================

@router.post(
    "/request",
    summary="Отправить заявку в друзья",
    description="Создаёт заявку со статусом 'pending'"
)
@limiter.limit(settings.RATE_LIMIT_FRIEND_REQUEST)
async def send_request(request: Request, data: FriendRequest, user_id: int = Depends(require_active_user)):
    """
    Принимает username пользователя, которому хотим отправить заявку
    Сервис ищет пользователя по username, проверяет что не себе и не дубликат
    """
    result = await friends_service.send_request(user_id, data.username)
    peer_id = int(result["peer_id"])
    payload = {
        "action": "friends_sync",
        "reason": "request_created",
        "from_user_id": user_id,
        "peer_user_id": peer_id,
    }
    await realtime_bus.emit_personal_event(user_id=user_id, payload=payload)
    await realtime_bus.emit_personal_event(user_id=peer_id, payload=payload)
    return {"message": "Заявка отправлена"}


@router.post(
    "/accept/{request_id}",
    summary="Принять заявку",
    description="Меняет статус заявки на 'accepted'"
)
@limiter.limit(settings.RATE_LIMIT_FRIEND_REQUEST)
async def accept_request(request: Request, request_id: int, user_id: int = Depends(require_active_user)):
    """
    Принимает входящую заявку.
    Проверяет что текущий пользователь — получатель заявки.
    """
    result = await friends_service.accept_request(user_id, request_id)
    peer_id = result["peer_id"]
    room_id = result["room_id"]
    readiness = await auth_service.get_direct_e2e_readiness(user_id, peer_id)

    await realtime_bus.emit_personal_event(
        user_id=user_id,
        payload={
            "action": "direct_room_ready",
            "room_id": room_id,
            "peer_id": peer_id,
            "e2e_ready": readiness.get("ready", False),
            "e2e_reason": readiness.get("reason"),
        },
    )
    await realtime_bus.emit_personal_event(
        user_id=peer_id,
        payload={
            "action": "direct_room_ready",
            "room_id": room_id,
            "peer_id": user_id,
            "e2e_ready": readiness.get("ready", False),
            "e2e_reason": readiness.get("reason"),
        },
    )
    sync_payload = {
        "action": "friends_sync",
        "reason": "request_accepted",
        "from_user_id": user_id,
        "peer_user_id": peer_id,
    }
    await realtime_bus.emit_personal_event(user_id=user_id, payload=sync_payload)
    await realtime_bus.emit_personal_event(user_id=peer_id, payload=sync_payload)
    await e2e_orchestrator.sync_direct_pair(user_id, peer_id, reason="friend_request_accepted")
    return {"message": "Заявка принята"}


@router.post(
    "/decline/{request_id}",
    summary="Отклонить заявку",
    description="Удаляет заявку из БД"
)
@limiter.limit(settings.RATE_LIMIT_FRIEND_REQUEST)
async def decline_request(request: Request, request_id: int, user_id: int = Depends(require_active_user)):
    """
    Отклоняет входящую заявку.
    Проверяет что текущий пользователь — получатель заявки.
    """
    result = await friends_service.decline_request(user_id, request_id)
    peer_id = int(result["peer_id"])
    await realtime_bus.emit_personal_event(
        user_id=user_id,
        payload={
            "action": "friends_sync",
            "reason": "request_declined",
            "from_user_id": user_id,
            "peer_user_id": peer_id,
        },
    )
    await realtime_bus.emit_personal_event(
        user_id=peer_id,
        payload={
            "action": "friends_sync",
            "reason": "request_declined",
            "from_user_id": user_id,
            "peer_user_id": peer_id,
        },
    )
    return {"message": "Заявка отклонена"}


@router.post(
    "/block/{target_user_id}",
    summary="Заблокировать пользователя",
    description="Помечает связь как blocked; повторные заявки от этой стороны невозможны",
)
@limiter.limit(settings.RATE_LIMIT_FRIEND_BLOCK)
async def block_user(request: Request, target_user_id: int, user_id: int = Depends(require_active_user)):
    await friends_service.block_user(user_id, target_user_id)
    affected_room_ids = await friends_service.enforce_block_for_direct_chat(user_id, target_user_id)
    payload_for_actor = {
        "action": "direct_blocked",
        "by_user_id": user_id,
        "target_user_id": target_user_id,
        "room_ids": affected_room_ids,
    }
    payload_for_target = {
        "action": "direct_blocked",
        "by_user_id": user_id,
        "target_user_id": target_user_id,
        "room_ids": affected_room_ids,
    }
    await realtime_bus.emit_personal_event(user_id=user_id, payload=payload_for_actor)
    await realtime_bus.emit_personal_event(user_id=target_user_id, payload=payload_for_target)
    sync_payload = {
        "action": "friends_sync",
        "reason": "user_blocked",
        "from_user_id": user_id,
        "peer_user_id": target_user_id,
    }
    await realtime_bus.emit_personal_event(user_id=user_id, payload=sync_payload)
    await realtime_bus.emit_personal_event(user_id=target_user_id, payload=sync_payload)
    return {"message": "Пользователь заблокирован"}


@router.post(
    "/unblock/{target_user_id}",
    summary="Разблокировать пользователя",
    description="Удаляет пользователя из вашего ЧС",
)
@limiter.limit(settings.RATE_LIMIT_FRIEND_BLOCK)
async def unblock_user(request: Request, target_user_id: int, user_id: int = Depends(require_active_user)):
    await friends_service.unblock_user(user_id, target_user_id)
    payload = {
        "action": "friends_sync",
        "reason": "user_unblocked",
        "from_user_id": user_id,
        "peer_user_id": target_user_id,
    }
    await realtime_bus.emit_personal_event(user_id=user_id, payload=payload)
    await realtime_bus.emit_personal_event(user_id=target_user_id, payload=payload)
    return {"message": "Пользователь разблокирован"}


@router.delete(
    "/{friend_id}",
    summary="Удалить из друзей",
    description="Удаляет запись о дружбе из БД"
)
async def remove_friend(friend_id: int, user_id: int = Depends(require_active_user)):
    """
    Полностью удаляет связь дружбы (обе записи — sender и receiver).
    """
    await friends_service.remove_friend(user_id, friend_id)
    await realtime_bus.emit_personal_event(
        user_id=user_id,
        payload={
            "action": "friends_sync",
            "reason": "friend_removed",
            "from_user_id": user_id,
            "peer_user_id": friend_id,
        },
    )
    await realtime_bus.emit_personal_event(
        user_id=friend_id,
        payload={
            "action": "friends_sync",
            "reason": "friend_removed",
            "from_user_id": user_id,
            "peer_user_id": friend_id,
        },
    )
    return {"message": "Удален из друзей"}


@router.get(
    "/",
    summary="Список друзей и заявок",
    description="Возвращает все записи дружбы текущего пользователя"
)
async def get_friends(user_id: int = Depends(require_active_user)):
    """
    Возвращает все записи Friendship, где участвует текущий пользователь.
    Это включает:
      - Входящие заявки (pending, где receiver_id == user_id)
      - Исходящие заявки (pending, где sender_id == user_id)
      - Принятые дружбы (accepted)
      - Заблокированные (blocked)

    Для каждой записи подтягивает информацию о втором участнике (партнёре).
    """
    response = await friends_service.get_friends_overview(user_id, manager.is_online)
    return {"friends": response}
