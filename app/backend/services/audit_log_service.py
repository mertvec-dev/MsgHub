from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import select

from database.engine import db_engine
from database.models.admin_audit_logs import AdminAuditLog
from database.models.security_events import SecurityEvent


class AuditLogService:
    async def log_admin_action(
        self,
        actor_user_id: int,
        action: str,
        target_user_id: Optional[int] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        async for session in db_engine.get_async_session():
            session.add(
                AdminAuditLog(
                    actor_user_id=actor_user_id,
                    target_user_id=target_user_id,
                    action=action,
                    details=details,
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:255] or None,
                )
            )
            await session.commit()
            return

    async def log_security_event(
        self,
        event_type: str,
        user_id: Optional[int] = None,
        severity: str = "info",
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        async for session in db_engine.get_async_session():
            session.add(
                SecurityEvent(
                    user_id=user_id,
                    event_type=event_type,
                    severity=severity,
                    details=details,
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:255] or None,
                )
            )
            await session.commit()
            return

    async def list_admin_audit_logs(self, limit: int = 100) -> list[AdminAuditLog]:
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(AdminAuditLog)
                .order_by(AdminAuditLog.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
            return list(res.scalars().all())

    async def list_security_events(self, limit: int = 100) -> list[SecurityEvent]:
        async for session in db_engine.get_async_session():
            res = await session.execute(
                select(SecurityEvent)
                .order_by(SecurityEvent.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )
            return list(res.scalars().all())


audit_log_service = AuditLogService()
