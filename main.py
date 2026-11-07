"""ASGI compatibility import of the canonical application factory."""
from app.http import create_app
app = create_app()
