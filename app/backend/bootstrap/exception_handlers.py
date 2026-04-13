"""Глобальные exception handlers FastAPI."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.backend.domain.errors import DomainError

_VALIDATION_MESSAGES_RU = {
    "string_too_short": "Поле слишком короткое",
    "string_too_long": "Поле слишком длинное",
    "string_pattern_mismatch": "Неверный формат поля",
    "missing": "Обязательное поле",
    "int_parsing": "Должно быть числом",
    "int_parsing_size": "Число слишком большое",
    "float_parsing": "Должно быть числом",
    "value_error.missing": "Обязательное поле",
    "min_length": "Минимум {min_length} символов",
    "max_length": "Максимум {max_length} символов",
    "less_than_equal": "Значение должно быть меньше или равно {le}",
    "greater_than_equal": "Значение должно быть больше или равно {ge}",
    "too_short": "Минимум {min_length} символов",
    "too_long": "Максимум {max_length} символов",
}


def _translate_pydantic_error(err: dict) -> str:
    """Переводит системное сообщение Pydantic на русский."""
    error_type = err.get("type", "")
    msg = err.get("msg", "")

    if msg and not any(char in msg for char in "abcdefghijklmnopqrstuvwxyz"):
        return msg

    template = _VALIDATION_MESSAGES_RU.get(error_type)
    if template:
        ctx = err.get("ctx", {})
        result = template
        for key, value in ctx.items():
            result = result.replace("{" + key + "}", str(value))
        return result

    return msg or "Ошибка валидации"


async def validation_exception_handler(_: Request, exc: ValidationError) -> JSONResponse:
    """Единый формат ответа на ошибки валидации."""
    translated = [
        {
            "loc": item.get("loc", []),
            "msg": _translate_pydantic_error(item),
            "type": item.get("type", "unknown"),
        }
        for item in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": translated})


async def domain_exception_handler(_: Request, exc: DomainError) -> JSONResponse:
    """Единый маппинг доменных ошибок в HTTP-ответ."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует все глобальные обработчики ошибок."""
    app.add_exception_handler(ValidationError, validation_exception_handler)
    app.add_exception_handler(DomainError, domain_exception_handler)

