"""
Валидация и хэширование паролей

Используем:
  - passlib + bcrypt — для хэширования (медленный, устойчив к брутфорсу).
  - Собственную валидацию — минимальные требования к паролю.

Асинхронность:
  - bcrypt — CPU-ёмкая операция.
  - hash_password_async — выполняет в ThreadPoolExecutor.
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import asyncio
from concurrent.futures import ThreadPoolExecutor

from passlib.context import CryptContext


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

# CryptContext — управляет алгоритмом хэширования
# bcrypt автоматически добавляет соль (salt) и делает множество раундов
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Пул потоков для асинхронных операций
executor = ThreadPoolExecutor()


# ============================================================================
# ВАЛИДАЦИЯ ПАРОЛЯ
# ============================================================================

def validate_password(password: str) -> bool:
    """
    Проверяет пароль на минимальные требования.

    Правила:
    1. Минимум 8 символов.
    2. Хотя бы одна цифра.
    3. Хотя бы одна заглавная буква.
    """
    if len(password) < 8:
        return False

    has_digit = any(char.isdigit() for char in password)
    if not has_digit:
        return False

    has_upper = any(char.isupper() for char in password)
    if not has_upper:
        return False

    return True


# ============================================================================
# ХЭШИРОВАНИЕ
# ============================================================================

def hash_password(password: str) -> str:
    """
    Хэширует пароль через bcrypt.

    bcrypt автоматически:
    - Генерирует случайную соль.
    - Выполняет 12 раундов хэширования (по умолчанию).
    - Результат включает соль и параметры — можно хранить как есть.
    """
    return pwd_context.hash(password)


async def hash_password_async(password: str) -> str:
    """
    Хэширует пароль в отдельном потоке (не блокирует event loop).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, hash_password, password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Проверяет пароль против хэша.

    bcrypt извлекает соль из hashed_password и сравнивает.
    """
    return pwd_context.verify(plain_password, hashed_password)
