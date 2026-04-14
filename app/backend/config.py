"""
Конфигурация приложения — загрузка переменных из .env

Использует pydantic-settings:
  - Читает .env файл
  - Валидирует типы (int, str, и т.д.)
  - Предоставляет свойства (cors_origins) для вычисляемых значений
  - Автоматически генерирует SECRET_KEY если его нет
"""

import secrets
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


def _ensure_secret_key() -> str:
    """
    Генерирует SECRET_KEY если его нет в .env, и сохраняет туда

    При первом запуске — создаёт случайный 64-символьный ключ
    При повторных — читает из .env (чтобы токены оставались валидными)
    (написано нейросетью)
    """
    env_path = Path(".env")

    # Если .env есть — читаем из него
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("SECRET_KEY="):
                key = line.split("=", 1)[1].strip()
                if key and key not in ("", "your_secret_key_here"):
                    return key  # Уже есть, не трогаем

    # Генерируем новый ключ
    new_key = secrets.token_urlsafe(48)  # 48 символов

    # Сохраняем в .env
    if env_path.exists():
        # Добавляем/обновляем строку
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.startswith("SECRET_KEY="):
                lines[i] = f"SECRET_KEY={new_key}"
                updated = True
                break
        if not updated:
            lines.append(f"\nSECRET_KEY={new_key}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        env_path.write_text(f"SECRET_KEY={new_key}\n", encoding="utf-8")

    print(f"Сгенерирован новый SECRET_KEY (сохранён в .env)")
    return new_key


# Глобальная переменная — ключ генерируется один раз при импорте
_GENERATED_SECRET_KEY = _ensure_secret_key()


class Settings(BaseSettings):
    """
    Все настройки приложения в одном месте.

    Значения берутся из файла .env.
    Если переменной в .env нет — используется значение по умолчанию.
    """

    # ─── Общее ───
    PROJECT_NAME: str = "MsgHub"
    # Произвольная метка деплоя (подставьте в .env на сервере — видна в GET /health)
    MSGHUB_REVISION: str = "unknown"

    # ─── База данных (PostgreSQL) ───
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    DB_NAME: str
    DATABASE_URL: str  # Полный URL: postgresql+asyncpg://user:pass@host:port/db

    # ─── Redis ───
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str  # redis://host:port/db

    # ─── JWT (аутентификация) ───
    SECRET_KEY: str = _GENERATED_SECRET_KEY  # Генерируется автоматически, если нет в .env
    ALGORITHM: str = "HS256"      # Алгоритм подписи
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30    # Время жизни access-токена
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7       # Время жизни refresh-токена
    SESSION_EXPIRE_DAYS: int = 7             # Время жизни сессии в БД
    AUTH_COOKIE_SECURE: bool = False         # True в проде под HTTPS
    AUTH_COOKIE_SAMESITE: str = "lax"        # lax/strict/none

    # ─── Сервер ───
    HOST: str = "0.0.0.0"         # Адрес прослушивания
    PORT: int = 8000              # Порт
    SYSTEM_USER_ID: int = 0       # ID системного пользователя (для ботов и т.д.)

    # ─── CORS (разрешённые origin) ───
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins(self) -> List[str]:
        """
        Разбивает строку ALLOWED_ORIGINS по запятым.
        Возвращает список: ["http://localhost:5173", "https://myapp.com"]
        """
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # ─── Rate Limiting ───
    RATE_LIMIT_LOGIN: str = "5/minute"       # Auth-эндпоинты (брутфорс)
    RATE_LIMIT_DEFAULT: str = "100/minute"   # Остальные запросы
    RATE_LIMIT_MESSAGE: str = "30/minute"    # Отправка сообщений (спам)
    RATE_LIMIT_FRIEND_REQUEST: str = "15/minute"
    RATE_LIMIT_FRIEND_BLOCK: str = "20/minute"
    RATE_LIMIT_ROOM_INVITE: str = "20/minute"

    # ─── Логирование ───
    LOG_LEVEL: str = "INFO"  # DEBUG / INFO / WARNING / ERROR

    class Config:
        env_file = ".env"  # Путь к файлу с переменными

# Глобальный экземпляр — импортируется везде
settings = Settings()
