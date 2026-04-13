"""
Роутер комнат — создание, участники, приглашения, управление
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from fastapi import APIRouter, HTTPException, status, Depends, Request

import logging

# Pydantic-схемы для валидации
from app.backend.schemas.rooms import RoomCreate, RoomResponse
from app.backend.schemas.rooms import RoomMuteRequest

# Сервис комнат — бизнес-логика
from app.backend.services.rooms_service import room_service
from app.backend.services.auth_service import auth_service

# Получение user_id из JWT-токена
from app.backend.utils.jwt_utils import get_current_user

# WebSocket менеджер — для уведомлений
from app.backend.services.realtime_bus import realtime_bus
from app.backend.services.e2e_orchestrator import e2e_orchestrator
from app.backend.services.audit_log_service import audit_log_service
from app.backend.utils.rate_limiter import limiter
from app.backend.config import settings

# ORM-модели
from database.models.rooms import RoomType
from app.backend.schemas.e2e import (
    RoomKeyEnvelopeUpsertRequest,
    RoomKeyEnvelopeResponse,
    RoomKeyRotateResponse,
)

logger = logging.getLogger(__name__)

# ============================================================================
# РОУТЕР
# ============================================================================
router = APIRouter(prefix="/rooms", tags=["rooms"])


# ============================================================================
# ЭНДПОИНТЫ — Создание
# ============================================================================

@router.post(
    "/create",
    response_model=RoomResponse,
    summary="Создать групповую комнату",
    description="Создаёт группу и добавляет создателя + приглашённых"
)
async def create_room(data: RoomCreate, user_id: int = Depends(get_current_user)):
    """
    Создаёт групповую комнату (тип всегда GROUP, даже если в data другой).
    Создатель автоматически становится участником со статусом OWNER.
    Приглашённые добавляются со статусом MEMBER.

    После создания — уведомляет всех приглашённых через WebSocket и Redis Pub/Sub.
    """
    try:
        room = await room_service.create_room(
            creator_id=user_id,
            name=data.name,
            type=RoomType.GROUP,
            user_ids=data.user_ids,
        )

        logger.info(f"Комната создана: id={room.id}, creator={user_id}, invited={data.user_ids}")

        # Уведомляем каждого приглашённого
        for invited_id in data.user_ids:
            notification = {
                "action": "new_room",
                "room_id": room.id,
                "room_name": room.name,
                "room_type": room.type.value if hasattr(room.type, 'value') else str(room.type),
            }
            await realtime_bus.emit_personal_event(user_id=invited_id, payload=notification)

        return room
    except ValueError as e:
        # 400 — невалидные данные (пустое имя и т.д.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/direct/{target_user_id}",
    response_model=RoomResponse,
    summary="Создать личный чат (direct)",
    description="Создаёт комнату типа 'direct' между двумя пользователями"
)
async def create_direct(target_user_id: int, user_id: int = Depends(get_current_user)):
    """
    Создаёт личный чат между текущим пользователем и target_user_id.
    Если direct-чат уже существует — сервис вернёт существующий.
    """
    try:
        room = await room_service.create_direct_room(user_id, target_user_id)

        # Уведомляем собеседника о новом чате
        notification = {
            "action": "new_room",
            "room_id": room.id,
            "room_name": None,
            "room_type": "direct",
        }
        await realtime_bus.emit_personal_event(user_id=target_user_id, payload=notification)
        readiness = await auth_service.get_direct_e2e_readiness(user_id, target_user_id)
        await realtime_bus.emit_personal_event(
            user_id=user_id,
            payload={
                "action": "direct_room_ready",
                "room_id": room.id,
                "peer_id": target_user_id,
                "e2e_ready": readiness.get("ready", False),
                "e2e_reason": readiness.get("reason"),
            },
        )
        await realtime_bus.emit_personal_event(
            user_id=target_user_id,
            payload={
                "action": "direct_room_ready",
                "room_id": room.id,
                "peer_id": user_id,
                "e2e_ready": readiness.get("ready", False),
                "e2e_reason": readiness.get("reason"),
            },
        )
        await e2e_orchestrator.sync_direct_pair(user_id, target_user_id, reason="direct_room_created")

        return room
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ============================================================================
# ЭНДПОИНТЫ — Чтение
# ============================================================================

@router.get(
    "/my",
    response_model=list[RoomResponse],
    summary="Мои комнаты",
    description="Список всех комнат, где состоит текущий пользователь"
)
async def get_my_rooms(user_id: int = Depends(get_current_user)):
    """Возвращает комнаты, где пользователь — участник (не забанен)."""
    return await room_service.get_user_rooms(user_id)


@router.get(
    "/{room_id}/members",
    response_model=list[dict],
    summary="Участники комнаты",
    description="Список всех участников с их данными"
)
async def get_room_members(room_id: int, user_id: int = Depends(get_current_user)):
    """
    Возвращает id, nickname, username всех участников комнаты.
    Нужно фронтенду, чтобы показать имя собеседника в direct-чате.
    """
    return await room_service.get_room_members(room_id)


# ============================================================================
# ЭНДПОИНТЫ — Управление участниками
# ============================================================================

@router.post(
    "/invite",
    summary="Пригласить пользователя в комнату",
    description="Добавляет пользователя в комнату (если не забанен)"
)
@limiter.limit(settings.RATE_LIMIT_ROOM_INVITE)
async def invite_user(
    request: Request,
    room_id: int,
    user_id: int,
    actor_id: int = Depends(get_current_user)
):
    """
    actor_id — кто приглашает (из токена).
    user_id — кого приглашают.
    room_id — в какую комнату.

    Только админ/владелец комнаты может приглашать.
    """
    try:
        return await room_service.invite_to_room(room_id, user_id, actor_id)
    except ValueError as e:
        # 403 — нет прав или пользователь забанен
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.delete(
    "/kick",
    summary="Выгнать пользователя из комнаты",
    description="Удаляет участника из комнаты"
)
async def kick_user(
    room_id: int,
    user_id: int,
    actor_id: int = Depends(get_current_user)
):
    """
    actor_id — кто кикает.
    user_id — кого кикают.

    Только админ/владелец может кикать.
    """
    try:
        await room_service.del_user_from_room(room_id, user_id, actor_id)
        return {"message": "Кикнут"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.post(
    "/leave/{room_id}",
    summary="Выйти из комнаты",
    description="Удаляет текущего пользователя из комнаты"
)
async def leave_room(room_id: int, user_id: int = Depends(get_current_user)):
    """Пользователь сам выходит из комнаты."""
    try:
        await room_service.exit_from_room(room_id, user_id)
        return {"message": "Вышли из комнаты"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/ban",
    summary="Заблокировать пользователя в комнате",
    description="Меняет статус участника на 'banned'"
)
@limiter.limit(settings.RATE_LIMIT_ROOM_INVITE)
async def ban_user(
    request: Request,
    room_id: int,
    user_id: int,
    actor_id: int = Depends(get_current_user)
):
    """
    actor_id — кто банит.
    user_id — кого банят.

    Только админ/владелец может банить.
    """
    try:
        await room_service.ban_user(room_id, user_id, actor_id)
        return {"message": "Пользователь заблокирован"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================================
# ЭНДПОИНТЫ — Действия с данными
# ============================================================================

@router.post(
    "/clear/{room_id}",
    summary="Очистить историю сообщений",
    description="Удаляет все сообщения пользователя в данной комнате (только для себя)"
)
async def clear_history(room_id: int, user_id: int = Depends(get_current_user)):
    """
    Удаляет все сообщения, отправленные данным пользователем в этой комнате.
    Сообщения других участников НЕ удаляются.
    """
    try:
        await room_service.clear_history(room_id, user_id)
        return {"message": "История очищена"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/mute",
    summary="Тихий mute участника",
    description="Временно запрещает отправку сообщений в группе (timeout)",
)
@limiter.limit(settings.RATE_LIMIT_ROOM_INVITE)
async def mute_user(
    request: Request,
    payload: RoomMuteRequest,
    room_id: int,
    actor_id: int = Depends(get_current_user),
):
    try:
        await room_service.mute_user(
            room_id=room_id,
            user_id=payload.user_id,
            actor_id=actor_id,
            minutes=payload.minutes,
            reason=payload.reason,
        )
        await realtime_bus.emit_room_event(
            room_id=room_id,
            payload={
                "action": "member_muted",
                "room_id": room_id,
                "user_id": payload.user_id,
                "minutes": payload.minutes,
                "reason": payload.reason,
            },
        )
        return {"message": "Пользователь получил mute"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/unmute",
    summary="Снять mute участника",
)
@limiter.limit(settings.RATE_LIMIT_ROOM_INVITE)
async def unmute_user(
    request: Request,
    room_id: int,
    user_id: int,
    actor_id: int = Depends(get_current_user),
):
    try:
        await room_service.unmute_user(room_id=room_id, user_id=user_id, actor_id=actor_id)
        await realtime_bus.emit_room_event(
            room_id=room_id,
            payload={
                "action": "member_unmuted",
                "room_id": room_id,
                "user_id": user_id,
            },
        )
        return {"message": "mute снят"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete(
    "/self/{room_id}",
    summary="Удалить комнату для себя",
    description="Скрывает комнату из списка текущего пользователя"
)
async def delete_room_self(request: Request, room_id: int, user_id: int = Depends(get_current_user)):
    """
    Удаляет запись участника из room_members для текущего пользователя.
    Комната перестаёт появляться в списке «Мои комнаты».
    """
    try:
        await room_service.delete_room_for_self(room_id, user_id)
        actor = await auth_service.get_me(user_id)
        if bool(actor.is_admin):
            await audit_log_service.log_admin_action(
                actor_user_id=user_id,
                action="delete_chat_for_self",
                details=f"room_id={room_id}",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("User-Agent"),
            )
        return {"message": "Чат удален"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# ============================================================================
# ЭНДПОИНТЫ — Действия с публичными ключами E2E (сквозное шифрование сообщений)
# ============================================================================
@router.post(
    "/{room_id}/keys/upsert",
    summary="Сохраняет конверты room-key для версии",
    description="Пакетно upsert конвертов (encrypted room key) для участников комнаты"
)
async def upsert_room_key(
    room_id: int,
    payload: RoomKeyEnvelopeUpsertRequest,
    user_id: int = Depends(get_current_user),
):
    """
    Загружает на сервер набор конвертов для room key.

    Важно:
    - сервер НЕ видит исходный room key, только encrypted_key;
    - version control идет через key_version;
    - каждый элемент envelopes адресован конкретному user_id.
    """
    try:
        return await room_service.upsert_room_key(room_id, user_id, payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/{room_id}/keys/my",
    response_model=RoomKeyEnvelopeResponse,
    summary="Получить мой актуальный конверт ключа",
    description="Возвращает encrypted room key для текущего пользователя и текущей версии комнаты",
)
async def get_my_room_key(room_id: int, user_id: int = Depends(get_current_user)):
    """
    Возвращает только КОНВЕРТ текущего пользователя (my key envelope).

    Это безопаснее, чем отдавать конверты других участников:
    каждый клиент получает только свой encrypted_key и расшифровывает локально.
    """
    try:
        data = await room_service.get_room_key(room_id, user_id)
        return RoomKeyEnvelopeResponse(**data)
    except ValueError as e:
        detail = str(e)
        status_code = status.HTTP_404_NOT_FOUND if "не найден" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail)


@router.post(
    "/{room_id}/keys/rotate",
    response_model=RoomKeyRotateResponse,
    summary="Ротация версии room key",
    description="Повышает current_key_version комнаты на 1 (только admin/owner)",
)
async def rotate_room_key(room_id: int, user_id: int = Depends(get_current_user)):
    """
    Ротация не меняет старые сообщения — она открывает НОВУЮ версию ключа.
    Дальше клиент должен загрузить новые конверты через /keys/upsert.
    """
    try:
        data = await room_service.rotate_room_key(room_id, user_id)
        return RoomKeyRotateResponse(**data)
    except ValueError as e:
        detail = str(e)
        status_code = status.HTTP_403_FORBIDDEN if "прав" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail)