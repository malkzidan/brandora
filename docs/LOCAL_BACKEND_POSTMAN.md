# Local Backend / Postman handoff

The repositories remain independent. `app.local` is a loopback-only development
runner around the existing `/v2/ai/respond` route and Groq/deterministic pipeline.
It is never imported by `app.server` and must not replace the release command.
No Customer, Conversation or Message persistence is implemented here.

## Install and start

Use Python 3.12 or another version supported by the checked-in dependencies:

```sh
python -m venv .venv
# Windows:
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Linux/macOS:
.venv/bin/python -m pip install -r requirements-dev.txt
```

The Backend maintainer first runs the isolated setup described in
`brandora-backend/docs/ai-local-testing.md`. Obtain only its generated **AI**
configuration privately and save it as `.env.local` (ignored). Using your virtual
environment's Python, start:

```sh
python -m app.local --env-file .env.local
```

No machine-specific path is required. Backend's private signing key and owner
login credentials are never needed by AI. Never copy them into this repository.

## Local configuration names

- `APP_ENV=local`, `AI_LOCAL_ENABLED=true`, `AI_LOCAL_PORT=8000`.
- `AI_INTEGRATION_ENABLED=true` enables the route in this local process only.
- `AI_LOCAL_PROVIDER=rules` makes no provider calls even when a key exists.
- `AI_LOCAL_PROVIDER=groq` requires a privately supplied `GROQ_API_KEY`; existing
  `GROQ_MODELS` and `CHAT_*` budgets apply.
- `AI_SERVICE_TOKEN`: Backend to AI credential.
- `BACKEND_SERVICE_TOKEN`: distinct AI to Backend credential.
- `BACKEND_CONTEXT_PUBLIC_KEY`: corresponding Backend public RSA key only.
- `BACKEND_BASE_URL=http://127.0.0.1:3099`: the real isolated Backend runner.
- `BACKEND_TIMEOUT_SECONDS=5`, `INTEGRATION_TIMEOUT_SECONDS=25` (local maximum 25,
  leaving room under Backend's 30-second outbound timeout).

The local runner refuses nonlocal Backend origins, deployed Railway markers and
nonlocal APP_ENV. It binds to 127.0.0.1 only; public tunnels are unsupported.
It does not need database or owner JWT credentials.

## Postman workflow

Send to the Backend runner, not directly to FastAPI:

```http
POST http://127.0.0.1:3099/dev/ai/respond
Content-Type: application/json
X-Brandora-Local-Test: true

{"message":"بكام التيشيرت الأسود مقاس L؟"}
```

Only message text is accepted. Backend pins the isolated business, revalidates its
fixture OWNER membership, creates fresh synthetic IDs, signs the exact body and
calls the canonical route. AI reads real NestJS tools using its distinct service
credential and signed context. No service secrets enter Postman.

Inspect `X-AI-Understanding-Provider`, `X-AI-Reply-Provider`,
`X-Brandora-Live-Groq`, `X-Brandora-Tool-Calls`, `X-AI-History-Status` and
`X-Brandora-Test-Mode`. Groq mode alone is not proof of a model call: fallback is
possible. Claim live understanding/composition only when the respective provider
headers report `groq`; otherwise record the fallback. HTTP 200 or /ready alone
does not prove live model or database acceptance.

Each request is independent. Ask a complete question including the product name.
A follow-up such as "طب مقاس L بكام؟" has no prior history and must clarify.
Product discovery is bounded and does not guarantee exhaustive catalog coverage.

E0-3 fields remain intent, reply, requiresReview, orderCandidate. Candidates stay
null; Orders are disabled. Canonical output is bounded to 20000 code points and
65536 UTF-8 bytes for the serialized response. Oversized output returns sanitized
503. General legacy E0-3 schemas are unchanged.

## Tests and deployment checklist

```sh
python -m pytest -q -p no:cacheprovider tests/test_local_runner.py tests/test_canonical_integration.py tests/test_backend_client.py tests/test_backend_data.py tests/test_history_service.py tests/test_products_integration.py tests/test_customer_stock_regression.py
```

Set `PYTHON_DOTENV_DISABLED=1`, `AI_PROVIDER=rules` and empty provider keys for
offline tests. These suites mock Backend/model transports; they do not prove
two-service HTTP or live Groq. Backend's local HTTP verifier tests the real two
services and fresh PostgreSQL fixture separately.

Before production: approve Backend-owned conversation persistence, immutable
history boundaries/snapshots/idempotent replies; verify cross-business acceptance
and ingress trust; provision production credentials privately; verify live Groq
separately; obtain both owners' release approvals. Preserve `app.server` and its
Railway configuration. History timestamp/length alignment remains deferred.

Transition: synthetic request -> persisted inbound message -> signed AI request
-> authorized on-demand history -> atomically persisted AI reply.
Never infer chronology from random UUIDs or truncate stored messages silently.

## Ownership and handoff

See [Malak handoff](HANDOFF.md) for the reviewed file list and source-only packaging.
Cloudinary, image recognition and permanent Excel storage remain deferred.
