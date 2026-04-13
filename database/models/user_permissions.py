from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class UserPermission(SQLModel, table=True):
    __tablename__ = "user_permissions"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    permission: str = Field(index=True, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "permission", name="unique_user_permission"),
    )
