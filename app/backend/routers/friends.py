"""
Роутер друзей — заявки, принятие, отклонение, список друзей
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from fastapi import APIRouter, HTTPException, status, Depends

# Логирование вместо print()
import logging

# SQLModel-запросы к БД
from sqlmodel import select

# Pydantic-схемы
from app.backend.schemas.friends import FriendRequest

# Сервис друзей — бизнес-логика
from app.backend.services.friends_service import friends_service
from app.backend.services.rooms_service import room_service
from app.backend.services import pubsub

# Получение user_id из JWT-токена
from app.backend.utils.jwt_utils import get_current_user

# WebSocket менеджер — для отображения онлайн-статуса
from app.backend.websocket import manager

# Асинхронная сессия БД
from database.engine import db_engine

# ORM-модели
from database.models.users import User
from database.models.friendships import Friendship

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
async def send_request(data: FriendRequest, user_id: int = Depends(get_current_user)):
    """
    Принимает username пользователя, которому хотим отправить заявку
    Сервис ищет пользователя по username, проверяет что не себе и не дубликат
    """
    try:
        await friends_service.send_request(user_id, data.username)
        return {"message": "Заявка отправлена"}
    except ValueError as e:
        # 400 — пользователь не найден, уже в друзьях, или заявка уже есть
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/accept/{request_id}",
    summary="Принять заявку",
    description="Меняет статус заявки на 'accepted'"
)
async def accept_request(request_id: int, user_id: int = Depends(get_current_user)):
    """
    Принимает входящую заявку.
    Проверяет что текущий пользователь — получатель заявки.
    """
    try:
        await friends_service.accept_request(user_id, request_id)
        async for session in db_engine.get_async_session():
            fr = await session.execute(select(Friendship).where(Friendship.id == request_id))
            row = fr.scalars().first()
            if row:
                peer_id = row.sender_id if row.receiver_id == user_id else row.receiver_id
                direct_room = await room_service.create_direct_room(user_id, peer_id)
                event = {
                    "action": "direct_room_ready",
                    "room_id": direct_room.id,
                    "peer_id": peer_id,
                }
                await manager.send_personal_message(event, user_id)
                await manager.send_personal_message(
                    {
                        "action": "direct_room_ready",
                        "room_id": direct_room.id,
                        "peer_id": user_id,
                    },
                    peer_id,
                )
                await pubsub.publish_message(event)
                await pubsub.publish_message(
                    {
                        "action": "direct_room_ready",
                        "room_id": direct_room.id,
                        "peer_id": user_id,
                    }
                )
        return {"message": "Заявка принята"}
    except ValueError as e:
        # 404 — заявка не найдена или не принадлежит пользователю
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/decline/{request_id}",
    summary="Отклонить заявку",
    description="Удаляет заявку из БД"
)
async def decline_request(request_id: int, user_id: int = Depends(get_current_user)):
    """
    Отклоняет входящую заявку.
    Проверяет что текущий пользователь — получатель заявки.
    """
    try:
        await friends_service.decline_request(user_id, request_id)
        return {"message": "Заявка отклонена"}
    except ValueError as e:
        # 404 — заявка не найдена
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post(
    "/block/{target_user_id}",
    summary="Заблокировать пользователя",
    description="Помечает связь как blocked; повторные заявки от этой стороны невозможны",
)
async def block_user(target_user_id: int, user_id: int = Depends(get_current_user)):
    try:
        await friends_service.block_user(user_id, target_user_id)
        return {"message": "Пользователь заблокирован"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/{friend_id}",
    summary="Удалить из друзей",
    description="Удаляет запись о дружбе из БД"
)
async def remove_friend(friend_id: int, user_id: int = Depends(get_current_user)):
    """
    Полностью удаляет связь дружбы (обе записи — sender и receiver).
    """
    try:
        await friends_service.remove_friend(user_id, friend_id)
        return {"message": "Удален из друзей"}
    except ValueError as e:
        # 400 — запись не найдена
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/",
    summary="Список друзей и заявок",
    description="Возвращает все записи дружбы текущего пользователя"
)
async def get_friends(user_id: int = Depends(get_current_user)):
    """
    Возвращает все записи Friendship, где участвует текущий пользователь.
    Это включает:
      - Входящие заявки (pending, где receiver_id == user_id)
      - Исходящие заявки (pending, где sender_id == user_id)
      - Принятые дружбы (accepted)
      - Заблокированные (blocked)

    Для каждой записи подтягивает информацию о втором участнике (партнёре).
    """
    async for session in db_engine.get_async_session():
        # Получаем все записи дружбы, где пользователь — либо отправитель, либо получатель
        result = await session.execute(
            select(Friendship).where(
                (Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)
            )
        )
        friendships = result.scalars().all()

        # Для каждой записи находим партнёра и собираем ответ
        response = []
        for f in friendships:
            # Определяем кто второй участник
            partner_id = f.sender_id if f.receiver_id == user_id else f.receiver_id

            # Ищем информацию о партнёре
            partner_result = await session.execute(
                select(User).where(User.id == partner_id)
            )
            partner = partner_result.scalars().first()

            response.append({
                "id": f.id,
                "partner_id": partner_id,
                "nickname": partner.nickname if partner else f"User#{partner_id}",
                "username": partner.username if partner else "unknown",
                "status": f.status,
                "sender_id": f.sender_id,
                "receiver_id": f.receiver_id,
                "is_online": manager.is_online(partner_id),  # Проверка по WebSocket
                "created_at": f.created_at.isoformat() if f.created_at else None,
            })

        return {"friends": response}
