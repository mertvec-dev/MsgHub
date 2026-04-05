from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from database.models.friendships import FriendshipStatus

# === Запрос в друзья ===
class FriendRequest(BaseModel):
    """Запрос на добавление в друзья"""
    username: str

class FriendshipResponse(BaseModel):
    """Информация о заявке в друзья"""
    id: int
    sender_id: int
    receiver_id: int
    status: FriendshipStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True # Позволяет создавать FriendshipResponse из ORM-модели Friendship

class FriendInfo(BaseModel):
    """Информация о друге"""
    user_id: int
    nickname: str
    username: str
    avatar_url: Optional[str] = None
    status_message: Optional[str] = None
    is_online: bool = False  # Из Redis


class FriendsList(BaseModel):
    """Список друзей"""
    friends: list[FriendInfo]