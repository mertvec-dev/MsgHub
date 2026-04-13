"""
Роутер сообщений — отправка, получение, редактирование, непрочитанные
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Query, Request

logger = logging.getLogger(__name__)

# Сервис сообщений — бизнес-логика
from app.backend.services.messages_service import messages_service
from app.backend.schemas.messages import MessageCreate, MessageEditRequest, MessagePinRequest

# Сервис уведомлений — пометка прочитанных
from app.backend.services.notification_service import notification_service

# Получение user_id из JWT-токена
from app.backend.utils.jwt_utils import get_current_user

# WebSocket менеджер — для real-time отправки
from app.backend.websocket import manager

from app.backend.services.realtime_bus import realtime_bus

# Настройки (лимиты rate limiting)
from app.backend.config import settings
from app.backend.utils.rate_limiter import limiter

# БД
from database.models import User
from database.engine import db_engine
from sqlmodel import select

# ============================================================================
# РОУТЕР
# ============================================================================
router = APIRouter(prefix="/messages", tags=["messages"])


async def _notify_messages_read(room_id: int, reader_id: int) -> None:
    """Рассылает в комнату: кто-то прочитал переписку — отправители обновят ✓✓."""
    payload = {
        "action": "messages_read",
        "room_id": room_id,
        "reader_id": reader_id,
    }
    await realtime_bus.emit_room_event(room_id=room_id, payload=payload)


# ============================================================================
# ЭНДПОИНТЫ — Получение сообщений
# ============================================================================
# Важно: фиксированные пути (/unread/count, /send, …) ДО параметризованного /{room_id},
# иначе GET /messages/unread/count может совпасть с /{room_id}=«unread».

@router.get(
    "/unread/count",
    summary="Счётчик непрочитанных",
    description="Количество непрочитанных сообщений по каждой комнате"
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_unread_count(request: Request, user_id: int = Depends(get_current_user)):
    """
    Возвращает словарь {room_id: count} и общую сумму.
    Фронтенд использует для отображения бейджей с количеством на каждой комнате.
    """
    counts = await notification_service.get_unread_count(user_id)
    return {"unread_counts": counts, "total_unread": sum(counts.values())}


@router.get(
    "/read/{room_id}",
    summary="Пометить как прочитанные",
    description="Ручная пометка всех сообщений в комнате как прочитанных"
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def mark_as_read(request: Request, room_id: int, user_id: int = Depends(get_current_user)):
    """
    Обновляет запись в message_reads, фиксируя время последнего прочтения.
    """
    try:
        await notification_service.mark_room_as_read(room_id, user_id)
        await _notify_messages_read(room_id, user_id)
        return {"message": "Сообщения отмечены как прочитанные"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/{room_id}",
    summary="Получить сообщения комнаты",
    description="Cursor-based пагинация: от новых к старым"
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def get_room_messages(
    room_id: int,
    request: Request,
    user_id: int = Depends(get_current_user),
    limit: int = Query(
        default=50,
        le=100,
        description="Максимум сообщений за раз (по умолчанию 50, максимум 100)"
    ),
    cursor: Optional[int] = Query(
        default=None,
        description="ID последнего загруженного сообщения (для подгрузки истории при скролле вверх)"
    ),
):
    """
    Загружает сообщения из комнаты.

    **Как работает cursor:**
    - cursor=None → загрузить самые новые 50 сообщений.
    - cursor=123 → загрузить 50 сообщений СТАРШЕ сообщения с ID=123.

    **Автоматическая пометка:**
    При просмотре сообщений сервис автоматически помечает их как прочитанные.

    **Проверка прав:**
    Если пользователь не состоит в комнате — возвращает 403.
    """
    try:
        data = await messages_service.get_messages(room_id, user_id, limit, cursor)

        # Помечаем все просмотренные сообщения как прочитанные
        await notification_service.mark_room_as_read(room_id, user_id)
        await _notify_messages_read(room_id, user_id)

        return data
    except ValueError as e:
        # 403 — пользователь не состоит в комнате
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


# ============================================================================
# ЭНДПОИНТЫ — Отправка и редактирование
# ============================================================================

@router.post(
    "/send",
    summary="Отправить сообщение",
    description="Сохраняет в БД, публикует в Redis, отправляет через WebSocket"
)
@limiter.limit(settings.RATE_LIMIT_MESSAGE)
async def send_message(
    request: Request,
    payload: MessageCreate,
    user_id: int = Depends(get_current_user),
):
    """
    Полный цикл отправки сообщения.
    """
    try:
        # 1. Сохраняем сообщение в БД
        msg = await messages_service.send_message(
            sender_id=user_id,
            room_id=payload.room_id,
            content=payload.content,
            nonce=payload.nonce,
            key_version=payload.key_version,
            sender_device_id=payload.sender_device_id,
            reply_to_message_id=payload.reply_to_message_id,
        )

        # Получаем никнейм отправителя для WebSocket (быстрый запрос)
        async for session in db_engine.get_async_session():
            res = await session.execute(select(User.nickname, User.is_admin).where(User.id == user_id))
            sender_row = res.first()
            sender_nickname = sender_row.nickname if sender_row else "Unknown"
            sender_is_admin = bool(sender_row.is_admin) if sender_row else False

        # 2. Подготавливаем данные для рассылки
        message_data = {
            "action": "new_message",
            "id": msg.id,
            "room_id": msg.room_id,
            "sender_id": user_id,
            "sender_nickname": sender_nickname,
            "sender_is_admin": sender_is_admin,
            "sender_device_id": msg.sender_device_id,
            "reply_to_message_id": msg.reply_to_message_id,
            "is_pinned": bool(getattr(msg, "is_pinned", False)),
            "pinned_by_user_id": getattr(msg, "pinned_by_user_id", None),
            "pinned_at": msg.pinned_at.isoformat() if getattr(msg, "pinned_at", None) else None,
            "pin_note": getattr(msg, "pin_note", None),
            "content": msg.content,
            "nonce": msg.nonce,
            "key_version": msg.key_version,
            "timestamp": msg.created_at.isoformat() if hasattr(msg.created_at, 'isoformat') else str(msg.created_at),
            "is_edited": msg.is_edited,
        }

        # 3. Отправляем через RealtimeBus (локальный WS + Redis)
        online = manager.get_users_in_room(msg.room_id)
        logger.info(f"📡 WebSocket broadcast: room={msg.room_id}, online_users={online}")
        await realtime_bus.emit_room_event(room_id=msg.room_id, payload=message_data)
        logger.info(f"✅ Broadcast завершён")

        return {
            "id": msg.id,
            "content": msg.content,
            "nonce": msg.nonce,
            "key_version": msg.key_version,
            "sender_device_id": msg.sender_device_id,
            "reply_to_message_id": msg.reply_to_message_id,
            "timestamp": msg.created_at.isoformat() if hasattr(msg.created_at, 'isoformat') else str(msg.created_at),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put(
    "/edit/{message_id}",
    summary="Редактировать сообщение",
    description="Изменяет текст сообщения (только автор может)"
)
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def edit_message(
    request: Request,
    message_id: int,
    payload: MessageEditRequest,
    user_id: int = Depends(get_current_user),
):
    """
    Полный цикл редактирования:

    1. Находит сообщение по ID.
    2. Проверяет что текущий пользователь — автор.
    3. Обновляет E2E-данные сообщения.
    4. Обновляет запись в БД (content, nonce, key_version, is_edited, edited_at).
    5. Публикует в Redis Pub/Sub.
    6. Отправляет через WebSocket всем в комнате (включая автора — чтобы обновить UI).
    """
    try:
        # 1. Редактируем в БД
        msg = await messages_service.edit_message(
            message_id=message_id,
            user_id=user_id,
            new_content=payload.content,
            nonce=payload.nonce,
            key_version=payload.key_version,
        )

        # 2. Подготавливаем данные
        message_data = {
            "action": "message_edited",
            "id": msg.id,
            "room_id": msg.room_id,
            "content": msg.content,
            "nonce": msg.nonce,
            "key_version": msg.key_version,
            "timestamp": msg.edited_at.isoformat() if hasattr(msg.edited_at, 'isoformat') else str(msg.edited_at),
        }

        # 3. Отправляем через RealtimeBus (локальный WS + Redis)
        await realtime_bus.emit_room_event(room_id=msg.room_id, payload=message_data)

        return {"message": "Сообщение отредактировано"}
    except ValueError as e:
        # 403 — не автор или сообщение не найдено
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )


@router.delete("/{message_id}", summary="Удалить сообщение")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_message(
    request: Request,
    message_id: int,
    user_id: int = Depends(get_current_user),
):
    """
    Удаляет сообщение (только автор).
    Уведомляет комнату через WebSocket, чтобы удалить из UI.
    """
    try:
        room_id = await messages_service.delete_message(message_id, user_id)

        # Уведомляем всех через WebSocket
        message_data = {
            "action": "message_deleted",
            "id": message_id,
            "room_id": room_id,
        }
        await realtime_bus.emit_room_event(room_id=room_id, payload=message_data)

        return {"message": "Сообщение удалено"}
    except ValueError as e:
        detail = str(e)
        if "не найдено" in detail:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.post("/pin/{room_id}/{message_id}", summary="Закрепить сообщение")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def pin_message(
    request: Request,
    room_id: int,
    message_id: int,
    payload: MessagePinRequest,
    user_id: int = Depends(get_current_user),
):
    try:
        msg = await messages_service.pin_message(
            room_id=room_id,
            message_id=message_id,
            actor_id=user_id,
            pin_note=payload.pin_note,
        )
        await realtime_bus.emit_room_event(
            room_id=room_id,
            payload={
                "action": "message_pinned",
                "room_id": room_id,
                "id": msg.id,
                "pinned_by_user_id": msg.pinned_by_user_id,
                "pinned_at": msg.pinned_at.isoformat() if msg.pinned_at else None,
                "pin_note": msg.pin_note,
            },
        )
        return {"message": "Сообщение закреплено"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/unpin/{room_id}/{message_id}", summary="Открепить сообщение")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def unpin_message(
    request: Request,
    room_id: int,
    message_id: int,
    user_id: int = Depends(get_current_user),
):
    try:
        msg = await messages_service.unpin_message(
            room_id=room_id,
            message_id=message_id,
            actor_id=user_id,
        )
        await realtime_bus.emit_room_event(
            room_id=room_id,
            payload={
                "action": "message_unpinned",
                "room_id": room_id,
                "id": msg.id,
            },
        )
        return {"message": "Сообщение откреплено"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
