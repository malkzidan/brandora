"""Environment-driven settings. Nothing secret is ever logged or echoed back."""
from __future__ import annotations

import os
from dataclasses import dataclass, field






class ConfigError(RuntimeError):
    """Invalid configuration; the service refuses to start (fail fast)."""


@dataclass(frozen=True)
class Settings:
    ai_provider: str = "rules"                  # Groq inference or deterministic Python
    groq_api_key: str | None = field(default=None, repr=False)
    groq_models: tuple[str, ...] = ("openai/gpt-oss-120b",)
    chat_provider_timeout_seconds: float = 3.0
    chat_total_timeout_seconds: float = 8.0
    chat_circuit_seconds: float = 30.0
    generator_enabled: bool = True               # false = Router only, replies come straight from the verified templates
    ai_service_token: str | None = field(default=None, repr=False)  # Backend -> AI only
    app_env: str = "local"
    products_integration_enabled: bool = False
    ai_integration_enabled: bool = False
    supplied_context_compat_enabled: bool = False
    legacy_api_enabled: bool = False
    trusted_proxy_cidrs: tuple[str, ...] = ()
    integration_timeout_seconds: float = 25.0
    stock_quantity_disclosure_businesses: tuple[str, ...] = ()
    backend_base_url: str | None = None
    backend_service_token: str | None = field(default=None, repr=False)  # AI -> Backend only
    backend_context_public_key: str | None = field(default=None, repr=False)
    backend_timeout_seconds: float = 5.0
    enable_dev_endpoints: bool = False           # /v1/dev/* (mock data playground). Never enable in production.
    log_level: str = "INFO"

    @property
    def router_models(self):
        return self.groq_models

    @property
    def generator_models(self):
        return self.groq_models

    @property
    def llm_enabled(self) -> bool:
        return self.ai_provider == "groq"

    def validate(self) -> "Settings":
        import math, ipaddress, hmac
        from urllib.parse import urlsplit
        if self.app_env not in {"local", "test", "staging", "production"}:
            raise ConfigError("APP_ENV must be local, test, staging or production")
        if self.ai_provider not in {"groq", "rules"}:
            raise ConfigError("AI_PROVIDER must be groq or rules")
        if self.ai_provider == "groq" and not self.groq_api_key:
            raise ConfigError("Groq requires GROQ_API_KEY")
        from dataclasses import fields
        for f in fields(self):
            if isinstance(f.default,bool) and type(getattr(self,f.name)) is not bool:
                raise ConfigError(f"{f.name.upper()} must be boolean")
        if self.groq_api_key is not None and (not isinstance(self.groq_api_key,str)
                or not self.groq_api_key.strip() or self.groq_api_key != self.groq_api_key.strip()):
            raise ConfigError("Invalid GROQ_API_KEY")
        if any((self.legacy_api_enabled,self.products_integration_enabled,
                self.supplied_context_compat_enabled,self.enable_dev_endpoints)):
            raise ConfigError("Removed route switches must be false")
        for name,maximum in (("chat_provider_timeout_seconds",25),("chat_total_timeout_seconds",25),
                ("chat_circuit_seconds",3600),("backend_timeout_seconds",25),("integration_timeout_seconds",25)):
            value=getattr(self,name)
            if type(value) not in {int,float} or not math.isfinite(value) or not 0 < value <= maximum:
                raise ConfigError(f"Invalid {name.upper()}")
        if self.log_level not in {"DEBUG","INFO","WARNING","ERROR","CRITICAL"}:
            raise ConfigError("Invalid LOG_LEVEL")
        if (not isinstance(self.groq_models,tuple) or not 1 <= len(self.groq_models) <= 4
                or any(not isinstance(m,str) or not m.strip() or len(m)>200 for m in self.groq_models)):
            raise ConfigError("GROQ_MODELS requires one to four model IDs")
        try:
            for cidr in self.trusted_proxy_cidrs:
                if ipaddress.ip_network(cidr,strict=True).prefixlen == 0:
                    raise ValueError()
            from uuid import UUID
            for business in self.stock_quantity_disclosure_businesses:
                if str(UUID(business)) != business:
                    raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ConfigError("Invalid proxy CIDR or disclosure business UUID") from None
        release=self.app_env in {"staging","production"}
        if release and (not self.ai_integration_enabled or self.ai_provider != "groq"):
            raise ConfigError("Release requires canonical integration and Groq configuration")
        if release and not self.trusted_proxy_cidrs:
            raise ConfigError("Release requires verified TRUSTED_PROXY_CIDRS")
        if self.backend_base_url:
            try:
                url=urlsplit(self.backend_base_url)
                if (url.scheme not in {"http","https"} or not url.hostname or url.username or url.password
                        or url.path not in {"","/"} or url.query or url.fragment or url.port == 0
                        or (url.scheme == "http" and url.hostname not in {"localhost","127.0.0.1","::1"})
                        or (release and url.scheme != "https")):
                    raise ValueError()
            except ValueError:
                raise ConfigError("Backend URL requires HTTPS origin or local loopback HTTP") from None
        if self.ai_integration_enabled:
            def valid(t):
                return isinstance(t,str) and 32 <= len(t) <= 4096 and all(33 <= ord(c) <= 126 for c in t)
            if (not valid(self.ai_service_token) or not valid(self.backend_service_token)
                    or hmac.compare_digest(self.ai_service_token,self.backend_service_token)
                    or not self.backend_base_url or not self.backend_context_public_key):
                raise ConfigError("Integration requires distinct credentials, Backend origin and RS256 public key")
            try:
                from cryptography.hazmat.primitives.serialization import load_pem_public_key
                from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
                key=load_pem_public_key(self.backend_context_public_key.encode("ascii"))
                if not isinstance(key,RSAPublicKey) or key.key_size < 2048:
                    raise ValueError()
            except Exception:
                raise ConfigError("Invalid Backend RSA public key (minimum 2048 bits)") from None
        return self


def parse_port(raw: str) -> int:
    if not raw.isascii() or not raw.isdecimal() or not 1 <= int(raw) <= 65535:
        raise ConfigError("PORT must be an integer from 1 to 65535")
    return int(raw)


def load_settings() -> Settings:
    from dataclasses import fields
    defaults=Settings()
    values={}
    for f in fields(defaults):
        raw=os.getenv(f.name.upper())
        if raw is None:
            continue
        default=getattr(defaults,f.name)
        try:
            if isinstance(default,bool):
                if raw.lower() not in {"true","false","1","0"}:
                    raise ValueError()
                value=raw.lower() in {"true","1"}
            elif isinstance(default,float):
                value=float(raw)
            elif isinstance(default,tuple):
                value=tuple(item.strip() for item in raw.split(",")) if raw else ()
                if any(not item for item in value):
                    raise ValueError()
            else:
                value=raw if raw else None
                if f.name=="backend_context_public_key" and value:
                    value=value.replace("\\n","\n")
            values[f.name]=value
        except (ValueError,TypeError):
            raise ConfigError(f"Invalid {f.name.upper()}") from None
    # Validate even when the ASGI factory is not called by an operator utility.
    return Settings(**values).validate()
