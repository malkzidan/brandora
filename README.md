# Brandora AI

FastAPI service for grounded, read-only customer product enquiries. Malak
maintains and deploys this repository independently from the NestJS Backend.

## Stack and architecture

Python, FastAPI, Pydantic, HTTPX and Groq. The canonical pipeline uses Groq for
structured interpretation and constrained replies, with deterministic fallback.
Python controls bounded retrieval; Backend owns authorization, prices and stock.

## Capabilities

- Product discovery, dynamic variant options, prices and availability.
- Signed service context and business-scoped read-only Backend tools.
- On-demand authorized history when Backend persistence is available.
- E0-3 responses: intent, reply, requiresReview and orderCandidate.
- Clarification when evidence, option selection or history is insufficient.

## Local setup

Use Python 3.12 or another version supported by [requirements](requirements.txt):

```sh
python -m venv .venv
```

Activate that environment, then install development dependencies:

```sh
python -m pip install -r requirements-dev.txt
```

Use `.env.example` as a template; keep private settings out of Git. For real
local Backend reads, obtain only the generated AI configuration fragment and run:

```sh
python -m app.local --env-file .env.local
```

See the [local Postman guide](docs/LOCAL_BACKEND_POSTMAN.md) for environment
activation, keys, loopback startup and the isolated Backend fixture.

## Tests

In a clean local test terminal, disable implicit dotenv loading and use rules:

```powershell
$env:PYTHON_DOTENV_DISABLED='1'
$env:AI_PROVIDER='rules'
python -m pytest -q -p no:cacheprovider
```

These tests use deterministic or mocked transports. They do not prove live Groq
or production readiness. See [handoff and verification](docs/HANDOFF.md).

## API and current status

Canonical endpoint: `POST /v2/ai/respond`. Its five-field request and signed
context are described in the [contract handoff](docs/FINAL_BACKEND_AI_HANDOFF.md).
The local harness supports independent synthetic messages over real local HTTP.
Production Conversations remain deferred; integration is disabled by default.
Live Groq is unverified, orderCandidate stays null, and Orders are not created.
Cloudinary, image recognition and permanent Excel storage are separate work.

Production continues to use `python -m app.server` and the existing Railway
configuration. `/ready` checks configuration, not live Backend/Groq acceptance.
See [release readiness](docs/BRANDORA_RAILWAY_READINESS.md); deployment requires
separate owner approval. The development runner is never the production entry point.
