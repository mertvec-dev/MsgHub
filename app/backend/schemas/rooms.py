from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from database.models.rooms import RoomType
from database.models.room_member import MembershipStatus as MemberStatus


# === Создание комнаты ===
class RoomCreate(BaseModel):
    """Создание комнаты"""
    name: Optional[str] = Field(default=None, max_length=100)
    type: RoomType = Field(default=RoomType.GROUP)
    user_ids: list[int] = Field(default=[])
    current_key_version: int = Field(default=1)

    @field_validator("name")
    @classmethod
    def validate_room_name(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.strip():
            raise ValueError("Название комнаты не может быть пустым")
        return v


# === Информация о комнате ===
class RoomResponse(BaseModel):
    """Информация о комнате (список «мои чаты» может добавлять превью и собеседника в direct)"""
    id: int
    name: Optional[str]
    type: RoomType
    current_key_version: int = Field(default=1)
    created_by: int
    created_at: datetime
    updated_at: datetime
    last_message: Optional[str] = None
    last_message_sender: Optional[str] = None
    partner_id: Optional[int] = None
    partner_nickname: Optional[str] = None
    partner_username: Optional[str] = None

    class Config:
        from_attributes = True # Позволяет создавать RoomResponse из ORM-модели Room


# === Участник комнаты ===
class RoomMemberResponse(BaseModel):
    """Информация об участнике"""
    user_id: int
    nickname: str
    username: str
    status: MemberStatus
    joined_at: datetime
    
    class Config:
        from_attributes = True # Позволяет создавать RoomMemberResponse из ORM-модели RoomMember


class RoomMembersList(BaseModel):
    """Список участников"""
    members: list[RoomMemberResponse]


# === Приглашение ===
class InviteUserRequest(BaseModel):
    """Пригласить пользователя"""
    user_id: int


class RoomMuteRequest(BaseModel):
    user_id: int
    minutes: int = Field(..., ge=1, le=24 * 60)
    reason: Optional[str] = Field(default=None, max_length=255)