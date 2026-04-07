from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
import re

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

# === Выход ===
class LogoutResponse(BaseModel):
    """Ответ после выхода"""
    message: str = "Успешный выход"