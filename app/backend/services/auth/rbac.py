from __future__ import annotations

from typing import Dict, Set

from database.models.users import UserRole


class Permission:
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    BAN_USERS = "ban_users"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_ROOMS = "manage_rooms"
    MUTE_MEMBERS = "mute_members"


ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    UserRole.USER.value: set(),
    UserRole.MODERATOR.value: {
        Permission.BAN_USERS,
        Permission.MANAGE_ROOMS,
        Permission.MUTE_MEMBERS,
        Permission.VIEW_AUDIT_LOGS,
    },
    UserRole.SUPER_ADMIN.value: {
        Permission.MANAGE_USERS,
        Permission.MANAGE_ROLES,
        Permission.BAN_USERS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.MANAGE_ROOMS,
        Permission.MUTE_MEMBERS,
    },
}


def effective_permissions(role: str, extra_permissions: set[str] | None = None) -> set[str]:
    base = set(ROLE_PERMISSIONS.get(role, set()))
    if extra_permissions:
        base.update(extra_permissions)
    return base


def has_permission(role: str, permission: str, extra_permissions: set[str] | None = None) -> bool:
    return permission in effective_permissions(role, extra_permissions)
