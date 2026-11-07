"""Reviewed Railway launcher. Fail closed; no legacy providers or proxy wildcard."""
import os

from .config import ConfigError,load_settings


def create_application():
    settings=load_settings()
    if settings.app_env not in {"staging","production"} or not settings.ai_integration_enabled:
        raise ConfigError("Railway requires explicit APP_ENV staging/production and enabled canonical integration")
    if not settings.trusted_proxy_cidrs:
        raise ConfigError("Railway requires verified TRUSTED_PROXY_CIDRS; do not use wildcard proxy trust")
    if settings.enable_dev_endpoints:
        raise ConfigError("Railway must not enable development endpoints")
    from .http import create_app
    return create_app(settings)


def main():
    import uvicorn
    from .config import parse_port
    port=parse_port(os.getenv("PORT","8080"))
    uvicorn.run(create_application(),host="0.0.0.0",port=port,proxy_headers=False,
                access_log=False,timeout_keep_alive=5,limit_concurrency=64)


if __name__ == "__main__":
    main()
