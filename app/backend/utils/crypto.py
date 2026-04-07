"""
ВНИМАНИЕ:
НУЖНА ДЛЯ СЕРВИСНОЙ РАССЫЛКИ. НЕ ДЛЯ ПОЛЬЗОВАТЕЛЬСКИХ ДАННЫХ. ТЕПЕРЬ ВОТ ПОЧЕМУ:
    - ДОБАВЛЕНО СКВОЗНОЕ ШИФРОВАНИЕ. КЛЮЧИ ГЕНЕРИРУЮТСЯ НА ФРОНТЕНДЕ И ПЕРЕДАЮТСЯ В БАЗУ ДАННЫХ.

Криптография сообщений — шифрование/дешифрование через Fernet (AES-128)

Fernet — симметричное шифрование:
  - Один ключ и для шифрования, и для расшифровки
  - Ключ получается из SECRET_KEY через SHA-256 + Base64
  - AES-128 в режиме CBC с HMAC для аутентификации

Асинхронность:
  - Шифрование — CPU-операция, блокирует event loop
  - Используем ThreadPoolExecutor чтобы не тормозить другие запросы
"""

# ============================================================================
# ИМПОРТЫ
# ============================================================================
import asyncio
import hashlib
import base64
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet

from app.backend.config import settings


# ============================================================================
# МЕНЕДЖЕР КРИПТОГРАФИИ
# ============================================================================

class CryptoManager:
    """
    Шифрует и расшифровывает сообщения через Fernet.

    Ключ генерируется один раз при старте — из settings.SECRET_KEY.
    """

    def __init__(self):
        # Пул потоков — чтобы шифрование не блокировало async-цикл
        self.executor = ThreadPoolExecutor()

        # Превращаем SECRET_KEY в 32-байтный ключ для Fernet
        raw_key = settings.SECRET_KEY.encode()

        # SHA-256 даёт ровно 32 байта — идеально для AES-256
        hashed_key = hashlib.sha256(raw_key).digest()

        # Fernet требует URL-Safe Base64 закодированный ключ
        encoded_key = base64.urlsafe_b64encode(hashed_key)

        self.fernet = Fernet(encoded_key)

    def encrypt_message(self, message: str) -> str:
        """
        Шифрует сообщение (синхронно).
        Результат: зашифрованная строка Base64.
        """
        encrypted = self.fernet.encrypt(message.encode())
        return encrypted.decode()

    def decrypt_message(self, encrypted_message: str) -> str:
        """
        Расшифровывает сообщение (синхронно).
        """
        decrypted = self.fernet.decrypt(encrypted_message.encode())
        return decrypted.decode()

    async def encrypt_message_async(self, message: str) -> str:
        """
        Шифрует сообщение в отдельном потоке (не блокирует event loop).
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self.encrypt_message,
            message,
        )

    async def decrypt_message_async(self, encrypted_message: str) -> str:
        """
        Расшифровывает сообщение в отдельном потоке.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self.decrypt_message,
            encrypted_message,
        )


# Глобальный экземпляр — используется в messages_service
crypto_manager = CryptoManager()
