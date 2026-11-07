# Controlled staging configuration

No deployment was performed. Railway resources were not accessed.
railway.json retains `python -m app.server`, healthcheck /ready and on-failure
restart policy. The launcher binds 0.0.0.0 and strict dynamic PORT (default 8080),
disables unconditional proxy headers/access logging and caps Uvicorn concurrency.
SIGTERM uses Uvicorn's normal shutdown; no background model or Backend tasks are
started at application startup. HTTP clients close in per-call context managers.

Required release settings:

- APP_ENV=staging or production; AI_PROVIDER=groq; AI_INTEGRATION_ENABLED=true.
- GROQ_API_KEY and GROQ_MODELS (verify actual model access before rollout).
- AI_SERVICE_TOKEN and distinct BACKEND_SERVICE_TOKEN.
- BACKEND_BASE_URL (HTTPS origin); BACKEND_CONTEXT_PUBLIC_KEY (RSA public PEM).
- TRUSTED_PROXY_CIDRS (verified immediate ingress peers, never wildcard).
- PORT supplied by the host; optional LOG_LEVEL and bounded timeout settings.

JWT issuer/audience/scope are fixed contract constants documented in
[API_CONTRACT.md](API_CONTRACT.md), never permissive environment overrides.
Strict booleans accept true/false/1/0 only. Invalid configuration fails startup.
All obsolete route/development switches must remain false if supplied.
No Gemini/OpenRouter keys, model routing or dependency is used.

The checked-in .env.example contains placeholders only. The outbound service
credentials/public key and history settings align with the implemented receiver
and issuer on feature/backend-ai-integration. Real traffic still needs that
branch's reviewed release and a real conversation adapter. /ready reports configuration,
not successful Backend/Groq acceptance or Orders support.

Staging is ready to configure for controlled integration after Backend agreement.
Traffic readiness is blocked on the real Backend conversation adapter, an agreed
integration-branch release and verified ingress topology.
Railway proxy ranges must be established by an authenticated/isolated boundary;
do not guess CIDRs or trust spoofable forwarded headers. Live DNS/TLS, external
model access, host ingress isolation, distributed quotas and timeout behavior
remain infrastructure assumptions requiring controlled staging acceptance.
