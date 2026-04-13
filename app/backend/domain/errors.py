"""Типизированные доменные ошибки для единообразного маппинга в HTTP."""

from fastapi import status


class DomainError(Exception):
    """Базовая доменная ошибка с HTTP-статусом по умолчанию."""

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    """Сущность не найдена."""

    status_code = status.HTTP_404_NOT_FOUND


class ForbiddenError(DomainError):
    """Операция запрещена бизнес-правилами."""

    status_code = status.HTTP_403_FORBIDDEN


class ConflictError(DomainError):
    """Конфликт состояния (уже существует/уже обработано)."""

    status_code = status.HTTP_409_CONFLICT

