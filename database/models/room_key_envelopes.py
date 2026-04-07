from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from sqlalchemy import UniqueConstraint

class RoomKeyEnvelope(SQLModel, table=True):
    """
    Таблица `room_key_envelopes`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **room_id**: Ссылка на комнату (foreign key)
        **user_id**: Ссылка на пользователя (foreign key)
        **key_version**: Версия ключа для шифрования
        **encrypted_key**: Зашифрованный ключ для шифрования
        **algorithm**: Алгоритм ключа для шифрования
        **created_at**: Дата по UTC, создается СУБД при создании поля
        **updated_at**: Дата по UTC, обновляется СУБД при обновлении поля
    """
    __tablename__ = "room_key_envelopes"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="rooms.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    key_version: int = Field(default=1, index=True) # версия ключа для шифрования
    encrypted_key: str = Field(...) # зашифрованный ключ для шифрования
    algorithm: str = Field(default="x25519") # алгоритм ключа для шифрования

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (UniqueConstraint("room_id", "user_id", "key_version", name="unique_room_user_key_version"),) # чтобы не было двух ключей для одной и той же комнаты и пользователя с одной и той же версией ключа