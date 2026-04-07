from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class RoomType(str, Enum): 
    DIRECT = "direct"
    GROUP = "group"

class Room(SQLModel, table=True): 
    """
    Таблица `rooms`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **name**: Название комнаты
        **type**: Тип комнаты (direct, group)
        **created_by**: Ссылка на пользователя, который создал комнату (foreign key)
        **created_at**: Дата создания комнаты
        **updated_at**: Дата последнего обновления комнаты
    """
    __tablename__ = "rooms"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None)
    type: RoomType = Field(index=True)
    current_key_version: int = Field(default=1, index=True)
    created_by: int = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)