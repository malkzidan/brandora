# Brandora AI

**Development version ready for local integration testing. Not a production-ready release.**

One authenticated, read-only conversation engine: Groq for structured language
understanding and natural composition; Python for authorization, bounded tools,
Product/Variant evidence, deterministic policy and final response validation.

Canonical endpoint: `POST /v2/ai/respond`. Request: businessId, customerId,
conversationId, messageId, message. History is retrieved only when needed.
Response: intent, reply, requiresReview, orderCandidate=null. No Orders or stock
writes. Human review never implies that a notification was delivered.

Purchase intent now has a scoped, in-memory draft state: selection, quantity,
observed item subtotal, missing facts and explicit confirmation. Confirmation
revalidates Product evidence and returns an unavailable-submission response;
Backend Orders APIs and durable quotes do not yet exist. Nothing is persisted
or reserved by this AI. See [the current implementation handoff](docs/BACKEND_INTEGRATION.md#current-order-draft-contract--2026-11-08).

Production: `python -m app.server`. `main:app` uses the same FastAPI factory.
The checked-in Railway command is unchanged. No deployment was performed.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:AI_PROVIDER='rules'
.\.venv\Scripts\python -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python -m app.offline_demo --evaluate
```

The offline harness uses synthetic signed requests, Backend and Groq transports;
it never substitutes mocks into production. Release configuration fails closed.
No implicit .env loading occurs; see [.env.example](.env.example).

Backend feature/product-management and main were inspected at
`3f37c4c79f7caa5da99dc0f60f2e87f61e3d2b62`. Product Management DTOs are supported.
Backend `feature/backend-ai-integration` implements `/internal/ai/data` and the
OWNER-protected AI initiation route at `f7c826fc76bc0ab8569ae0ed25106ff19bdaae45`.
That code is absent from `main`; its registered conversation store intentionally
returns 503. Live Backend, real conversation persistence and live Groq remain
unverified. See the compatibility matrix in the Backend integration guide.

- [Architecture and V1/V2 decisions](docs/ARCHITECTURE.md)
- [Canonical API and integration-branch tool contract](docs/API_CONTRACT.md)
- [Backend compatibility and external tasks](docs/BACKEND_INTEGRATION.md)
- [Local/offline development](docs/LOCAL_DEVELOPMENT.md)
- [Testing and exact verification results](docs/TESTING.md)
- [Controlled staging configuration](docs/DEPLOYMENT.md)
