from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SecurityEvent(SQLModel, table=True):
    __tablename__ = "security_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    event_type: str = Field(index=True, max_length=64)
    severity: str = Field(default="info", max_length=16, index=True)
    details: Optional[str] = Field(default=None, max_length=2048)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
