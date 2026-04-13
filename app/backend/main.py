"""Точка входа backend-приложения MsgHub."""

from app.backend.bootstrap.create_app import create_app
from app.backend.bootstrap.logging_setup import configure_logging

configure_logging()
app = create_app()
