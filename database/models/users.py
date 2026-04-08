from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class User(SQLModel, table=True):
    """
    Таблица `users`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **nickname**: Уникален, индексируется
        **username**: Уникален, индексируется
        **password_hash**: хэшированный пароль
        **email**: Изначально равен None, уникален, индексируется
        **avatar_url**: URL аватара (опционально)
        **status_message**: Статус пользователя (опционально)
        **is_admin**: Является ли администратором
        **created_at**: Дата по UTC, создается СУБД при создании поля
        **updated_at**: Дата по UTC, обновляется СУБД при обновлении поля
    """
    __tablename__ = "users"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    nickname: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)
    
    password_hash: str = Field(...)
    
    email: Optional[str] = Field(default=None, unique=True, index=True)
    
    avatar_url: Optional[str] = Field(default=None)
    status_message: Optional[str] = Field(default=None)
    profile_tag: Optional[str] = Field(default=None, max_length=32)
    
    is_admin: bool = Field(default=False)
    is_banned: bool = Field(default=False, index=True)
    is_active: bool = Field(default=True, index=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)