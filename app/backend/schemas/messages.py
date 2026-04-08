from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

# === Отправка сообщения ===
class MessageCreate(BaseModel):
    """Создание E2E-сообщения (ciphertext + nonce + key_version)"""
    room_id: int = Field(..., gt=0)
    content: str = Field(..., min_length=1, max_length=8192)
    nonce: str = Field(..., min_length=12, max_length=12)
    key_version: int = Field(default=1, ge=1)
    sender_device_id: Optional[str] = Field(default=None, max_length=255)

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Сообщение не может быть пустым")
        return v


class MessageEditRequest(BaseModel):
    """Редактирование E2E-сообщения (новый ciphertext + nonce + key_version)"""
    content: str = Field(..., min_length=1, max_length=8192)
    nonce: str = Field(..., min_length=12, max_length=12)
    key_version: int = Field(default=1, ge=1)

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
    sender_device_id: Optional[str] = None
    sender_nickname: str 
    content: str
    nonce: str
    key_version: int
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