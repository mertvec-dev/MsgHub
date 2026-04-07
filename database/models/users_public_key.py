from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class UserPublicKey(SQLModel, table=True):
    """
    Таблица `user_public_keys`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **user_id**: Ссылка на пользователя (foreign key)
        **public_key**: Публичный ключ
        **algorithm**: Алгоритм ключа
        **created_at**: Дата создания ключа
        **updated_at**: Дата последнего обновления ключа
    """
    __tablename__ = "user_public_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)

    public_key: str = Field()
    algorithm: str = Field(default="x25519")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)