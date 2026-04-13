from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional
from datetime import datetime
import re
from database.models.users import UserRole

# === Регистрация ===
class RegisterRequest(BaseModel):
    """Схема для регистрации нового пользователя"""
    nickname: str = Field(..., min_length=3, max_length=50)
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("nickname", "username")
    @classmethod
    def validate_alphanumeric(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Может содержать только буквы, цифры и подчёркивания")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        return v

# === Вход ===
class LoginRequest(BaseModel):
    """Схема для входа пользователя"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    device_id: Optional[str] = Field(default=None, max_length=255)
    device_name: Optional[str] = Field(default=None, max_length=255)
    device_type: Optional[str] = Field(default=None, max_length=64)

class TokenResponse(BaseModel):
    """
    Данные авторизации для клиента.

    Используется в ответах POST /auth/register, /auth/login и /auth/refresh.
    refresh_token хранится только в HttpOnly-cookie, в JSON не возвращается.
    """
    access_token: str
    token_type: str = "bearer"
    user_id: int

# === Сессии ===
class SessionInfo(BaseModel):
    """Информация о сессии"""
    id: int
    device_id: Optional[str]
    device_info: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    expires_at: datetime
    last_active_at: datetime
    
    class Config:
        from_attributes = True

class SessionListResponse(BaseModel):
    """Схема для ответа со списком сессий"""
    sessions: list[SessionInfo]


class RevokeSessionResponse(BaseModel):
    message: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nickname: str
    username: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    status_message: Optional[str] = None
    profile_tag: Optional[str] = None
    role: UserRole = UserRole.USER
    is_admin: bool = False
    is_banned: bool = False
    is_active: bool = True


class ProfileUpdateRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, min_length=3, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    avatar_url: Optional[str] = Field(default=None, max_length=2048)
    status_message: Optional[str] = Field(default=None, max_length=255)
    profile_tag: Optional[str] = Field(default=None, max_length=32)


class AdminOverviewResponse(BaseModel):
    users_total: int
    admins_total: int
    banned_total: int
    rooms_total: int
    messages_total: int


class RoleUpdateRequest(BaseModel):
    role: UserRole


class PermissionUpdateRequest(BaseModel):
    permission: str = Field(..., min_length=2, max_length=64)


class AdminTagUpdateRequest(BaseModel):
    profile_tag: Optional[str] = Field(default=None, max_length=32)


class PermissionsResponse(BaseModel):
    permissions: list[str]


class AdminAuditLogResponse(BaseModel):
    id: int
    actor_user_id: int
    target_user_id: Optional[int] = None
    action: str
    details: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class SecurityEventResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    event_type: str
    severity: str
    details: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

# === Выход ===
class LogoutResponse(BaseModel):
    """Ответ после выхода"""
    message: str = "Успешный выход"