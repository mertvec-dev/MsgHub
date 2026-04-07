from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
from sqlalchemy import UniqueConstraint # для уникальности связи между пользователями

class FriendshipStatus(str, Enum): # статусы дружбы
    PENDING = "pending" # заявка отправлена
    ACCEPTED = "accepted" # дружба подтверждена
    BLOCKED = "blocked" # заблокирован

class Friendship(SQLModel, table=True):
    """
    Таблица `friendship`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **sender_id**: Ссылка на пользователя, который отправил запрос (foreign key)
        **receiver_id**: Ссылка на пользователя, которому отправлен запрос (foreign key)
        **status**: Статус дружбы (pending, accepted, blocked)
        **created_at**: Дата создания заявки
        **updated_at**: Дата обновления статуса
    """
    __tablename__ = "friendships"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    sender_id: int = Field(foreign_key="users.id", index=True)
    receiver_id: int = Field(foreign_key="users.id", index=True)

    status: FriendshipStatus = Field(default=FriendshipStatus.PENDING, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint("sender_id", "receiver_id", name="unique_sender_receiver"),)