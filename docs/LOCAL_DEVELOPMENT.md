# Local development

Python 3.13 is selected by .python-version. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:AI_PROVIDER='rules'
.\.venv\Scripts\python -m app.offline_demo --evaluate
.\.venv\Scripts\python -m app.offline_demo
```

The offline harness generates throwaway RSA keys and synthetic Backend/Groq
HTTP transports. It exercises the canonical signed endpoint and request-local
history. It never calls a live model or Backend. `python -m app.chat` delegates
to this same harness. Synthetic credentials are never production fallback.

For manual HTTP testing, `python -m app.offline_demo --serve` binds only
127.0.0.1:8787. Its extra /demo/context route issues synthetic context for known
fixture scopes only. It is never imported by production. The independent socket
check is `python -m tests.http_smoke` and starts/stops only this local process.

For an agreed, real local Backend S2S receiver, use a separate private env file
and `python -m app.local --env-file <private-file>`. Set AI_LOCAL_ENABLED=true,
APP_ENV=local, AI_LOCAL_PROVIDER=rules or groq, AI_LOCAL_PORT=8000, and canonical
integration credentials/key plus a loopback HTTP BACKEND_BASE_URL. Groq mode
requires GROQ_API_KEY and sends product/message content to Groq. Do not use
OWNER JWT credentials in this flow. The receiver exists on Backend
feature/backend-ai-integration, not main. Its separate local harness can supply
synthetic request identities and real disposable PostgreSQL domain reads. The
production AiModule still registers an unavailable conversation store. No local
PostgreSQL instance was supplied for the current audit, so the two-service
database harness remains blocked; do not create a database or use a cloud URL.

Configuration does not implicitly load .env. Only the explicit local runner
loads the specified private file. Do not change real secrets or existing .env.
The old development OWNER adapter is an isolated read-only utility, not an AI
service credential mechanism and not reachable through the canonical app.
