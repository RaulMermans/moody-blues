"""ASGI entrypoint: ``uvicorn moody_blues.main:app``."""

from moody_blues.api.app import create_app

app = create_app()
