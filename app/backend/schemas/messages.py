from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

# === Отправка сообщения ===
class MessageCreate(BaseModel):
    """Создание сообщения"""
    content: str = Field(..., min_length=1, max_length=4096)

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Сообщение не может быть пустым")
        return v

# === Информация о сообщении ===
class MessageResponse(BaseModel):
    """Информация о сообщении"""
    id: int
    room_id: int
    sender_id: int
    sender_nickname: str 
    content: str
    is_edited: bool
    edited_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class MessagesList(BaseModel):
    """Список сообщений"""
    messages: list[MessageResponse]
    total: int
    has_more: bool