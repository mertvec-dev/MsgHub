"""
Rate Limiting — ограничение частоты запросов

Используем slowapi — middleware для FastAPI.
Лимиты считаются по IP-адресу клиента.

Настройки берутся из config:
  - RATE_LIMIT_LOGIN     — для auth-эндпоинтов (5/мин)
  - RATE_LIMIT_MESSAGE   — для отправки сообщений (30/мин)
  - RATE_LIMIT_DEFAULT   — для остальных (100/мин)
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.backend.config import settings


# ============================================================================
# ЛИМИТЕР
# ============================================================================

# Глобальный экземпляр — подключается в main.py и используется в роутерах
limiter = Limiter(
    key_func=get_remote_address,  # Ключ = IP-адрес клиента
    default_limits=[settings.RATE_LIMIT_DEFAULT],  # Лимит по умолчанию
)
