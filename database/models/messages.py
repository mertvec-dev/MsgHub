from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Message(SQLModel, table=True):
    """
    Таблица `messages`

    Содержит поля:
        **id**: Уникален (автоинкремент)
        **room_id**: Ссылка на комнату (foreign key)
        **sender_id**: Кто отправил сообщение (foreign key на users.id)
        **content**: Зашифрованный текст сообщения
        **key_version**: Версия ключа для шифрования
        **nonce**: Параметр шифрования E2E (одноразовый) - берется из AES-GCM (т.е генератор случайных чисел для AES-GCM)
        **is_edited**: Было ли отредактировано
        **edited_at**: Дата редактирования (опционально)
        **created_at**: Дата и время отправки
    """
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)

    room_id: int = Field(foreign_key="rooms.id", index=True)
    sender_id: int = Field(foreign_key="users.id", index=True)
    sender_device_id: Optional[str] = Field(default=None, index=True)

    content: str = Field(...) # зашифрованный текст сообщения
    key_version: int = Field(default=1, index=True) # версия ключа для шифрования
    nonce: str = Field(..., min_length=12, max_length=12) # параметр шифрования E2E (одноразовый)

    is_edited: bool = Field(default=False)
    edited_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)