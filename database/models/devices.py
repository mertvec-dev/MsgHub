from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from sqlalchemy import UniqueConstraint

class Device(SQLModel, table=True):
    """
    Таблица `devices`
    
    Содержит поля:
        **id**: Уникален (автоинкремент)
        **user_id**: Ссылка на пользователя (foreign key)
        **device_id**: ID устройства
        **device_name**: Название устройства
        **device_type**: Тип устройства
        **last_active_at**: Дата последней активности устройства
        **created_at**: Дата создания устройства
    """
    __tablename__ = "devices"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    device_id: str = Field(index=True)
    device_name: Optional[str] = Field(default=None)
    device_type: Optional[str] = Field(default=None)
    last_active_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # public_key: str = Field() # публичный ключ устройства для шифрования TODO: раскомментировать после реализации multi-device и включить миграцию

    __table_args__ = (UniqueConstraint("user_id", "device_id", name="unique_user_device"),) # чтобы не было двух устройств для одного и того же пользователя с одним и тем же device_id