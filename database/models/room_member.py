from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
from sqlalchemy import UniqueConstraint

class MembershipStatus(str, Enum): 
    OWNER = "owner" # created_by в таблице Room
    ADMIN = "admin" # назначается владельцем комнаты
    MEMBER = "member" # обычный участник комнаты
    BANNED = "banned" # не может участвовать в комнате, назначается владельцем или администратором

class RoomMember(SQLModel, table=True):
    """
    Таблица `room_members`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **room_id**: Ссылка на комнату (foreign key)
        **user_id**: Ссылка на пользователя (foreign key)
        **joined_at**: Дата присоединения к комнате
        **status**: Статус участия в комнате
    """
    __tablename__ = "room_members"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="rooms.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    status: MembershipStatus = Field(default=MembershipStatus.MEMBER, index=True)

    __table_args__ = (UniqueConstraint("room_id", "user_id", name="unique_room_user"),) # для чтобы не было двух участников с одним и тем же room_id и user_id