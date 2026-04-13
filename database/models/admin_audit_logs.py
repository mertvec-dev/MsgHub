from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AdminAuditLog(SQLModel, table=True):
    __tablename__ = "admin_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor_user_id: int = Field(foreign_key="users.id", index=True)
    target_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    action: str = Field(index=True, max_length=64)
    details: Optional[str] = Field(default=None, max_length=2048)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
