from app.backend.utils.password_validator import (
    validate_password,
    hash_password,
    hash_password_async,
    verify_password
)
from app.backend.utils.jwt_utils import (
    create_access_token,
    verify_token,
    get_current_user,
    security
)
from app.backend.utils.crypto import crypto_manager

# Создаем ссылки на методы менеджера, чтобы старые импорты работали
encrypt_message = crypto_manager.encrypt_message
decrypt_message = crypto_manager.decrypt_message
encrypt_message_async = crypto_manager.encrypt_message_async
decrypt_message_async = crypto_manager.decrypt_message_async

__all__ = [
    # Пароли
    "validate_password",
    "hash_password",
    "hash_password_async",
    "verify_password",

    # JWT
    "create_access_token",
    "verify_token",
    "get_current_user",
    "security",

    # Шифрование
    "encrypt_message",
    "decrypt_message",
    "encrypt_message_async",
    "decrypt_message_async",
    "crypto_manager",
]