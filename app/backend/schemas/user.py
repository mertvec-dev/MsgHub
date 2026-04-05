from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
import re


class UserBase(BaseModel):
    """Базовая схема пользователя"""
    nickname: str = Field(..., min_length=3, max_length=50)
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    status_message: Optional[str] = Field(default=None, max_length=200)

    @field_validator("nickname", "username")
    @classmethod
    def validate_alphanumeric(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Может содержать только буквы, цифры и подчёркивания")
        return v


class UserCreate(UserBase):
    """Создание пользователя (при регистрации)"""
    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    """Ответ с информацией о пользователе"""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # Позволяет создавать UserResponse из ORM-модели User


class UserUpdate(BaseModel):
    """Обновление профиля"""
    nickname: Optional[str] = Field(default=None, min_length=3, max_length=50)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    status_message: Optional[str] = Field(default=None, max_length=200)