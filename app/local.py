"""Explicit loopback canonical runner, never the production entry point."""
import argparse
import os
from dataclasses import replace
from urllib.parse import urlsplit


def create_local_application():
    if (os.getenv("AI_LOCAL_ENABLED") != "true" or os.getenv("APP_ENV") != "local"
            or any(os.getenv(k) for k in
                   ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID"))):
        raise ValueError("Local AI runner is disabled outside explicit local configuration")
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from .config import load_settings
    settings = load_settings()
    origin = urlsplit(settings.backend_base_url or "")
    if (origin.scheme != "http" or origin.hostname not in {"localhost", "127.0.0.1", "::1"}
            or origin.username or origin.password or origin.path not in {"", "/"}
            or origin.query or origin.fragment):
        raise ValueError("Local runner requires a loopback Backend origin")
    if not settings.ai_integration_enabled or not 0 < settings.integration_timeout_seconds <= 25:
        raise ValueError("Local integration requires explicit activation and deadline at most 25 seconds")
    for token in (settings.ai_service_token, settings.backend_service_token):
        if not token or not 32 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError("Local credentials require 32..4096 non-whitespace ASCII characters")
    mode = os.getenv("AI_LOCAL_PROVIDER", "rules")
    if mode not in {"rules", "groq"}:
        raise ValueError("AI_LOCAL_PROVIDER must be rules or groq")
    if mode == "groq" and not settings.groq_api_key:
        raise ValueError("Groq mode requires a privately configured GROQ_API_KEY")
    from .http import create_app
    app = create_app(replace(
        settings, ai_provider=mode, legacy_api_enabled=False, enable_dev_endpoints=False,
        products_integration_enabled=False, supplied_context_compat_enabled=False,
        groq_api_key=settings.groq_api_key if mode == "groq" else None,
    ))
    app.state.local_provider_mode = mode

    @app.middleware("http")
    async def local_metadata(request, call_next):
        response = await call_next(request)
        response.headers["X-AI-Local-Mode"] = mode
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def main():
    parser = argparse.ArgumentParser(description="Loopback-only Brandora AI runner")
    parser.add_argument("--env-file", help="Explicit private local configuration")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import dotenv_values
        for name, value in dotenv_values(args.env_file).items():
            if value is not None:
                os.environ.setdefault(name, value)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    try:
        port = int(os.getenv("AI_LOCAL_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError()
        app = create_local_application()
    except Exception:
        raise SystemExit("Local AI runner refused startup; verify local-only configuration.") from None
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
