from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class MessageRead(SQLModel, table=True):
    """
    Таблица `message_reads`
    Отслеживает, кто прочитал какое сообщение.
    
    Нужно для групповых чатов (в личных достаточно is_read на сообщении)

    Содержит поля:
        **id**: Уникален (автоинкремент)
        **message_id**: Ссылка на сообщение (foreign key)
        **user_id**: Ссылка на пользователя (foreign key)
        **read_at**: Дата прочтения сообщения
    """
    __tablename__ = "message_reads"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="messages.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    read_at: datetime = Field(default_factory=datetime.utcnow)
