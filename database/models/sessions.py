from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class Session(SQLModel, table=True):
    """
    Таблица `sessions`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **user_id**: Ссылка на пользователя (foreign key)
        **refresh_token_hash**: Хэш refresh-токена
        **device_info**: Устройство (опционально)
        **ip_address**: IP адрес (опционально)
        **created_at**: Дата создания сессии
        **expires_at**: Дата истечения сессии
        **last_active_at**: Последняя активность
    """
    __tablename__ = "sessions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    refresh_token_hash: str = Field(index=True)
    device_id: Optional[str] = Field(default=None, index=True)
    
    device_info: Optional[str] = Field(default=None)
    ip_address: Optional[str] = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field()
    last_active_at: datetime = Field(default_factory=datetime.utcnow)