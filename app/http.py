"""Canonical FastAPI factory shared by release, local and offline testing."""
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .config import load_settings
from .ingress import IntegrationIngress


def create_app(settings=None, *, products_transport=None, products_model_client=None):
    settings=(settings or load_settings()).validate()
    logging.basicConfig(level=settings.log_level)
    for name in ("httpx","httpcore","urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    app=FastAPI(title="Brandora AI",version="2.0.0")
    app.state.settings=settings
    app.add_middleware(IntegrationIngress,trusted_proxy_cidrs=settings.trusted_proxy_cidrs)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request,error):
        return JSONResponse({"error":"VALIDATION_ERROR"},status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request: Request,error):
        logging.getLogger("brandora").error("Unhandled request failure")
        return JSONResponse({"error":"INTERNAL_ERROR"},status_code=500)

    @app.get("/health/live")
    @app.get("/health")
    @app.get("/")
    async def live():
        return {"service":"brandora-ai","status":"ok"}

    @app.get("/ready")
    async def ready():
        return JSONResponse({"status":"configured" if settings.ai_integration_enabled else "disabled",
                             "backendLiveVerified":False,"ordersEnabled":False},
                            status_code=200 if settings.ai_integration_enabled else 503)

    if settings.ai_integration_enabled:
        from .api import build_conversation_router
        app.include_router(build_conversation_router(settings,transport=products_transport,model_client=products_model_client))
    return app
