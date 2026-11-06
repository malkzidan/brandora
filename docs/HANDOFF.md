# AI handoff to Malak

This repository remains independent from shrouqshaker/brandora-backend.
Review all local changes before publishing. The integration baseline reviewed
for this work was a65969f26799cb6ec1616b10c0d6ef240d55ef6c; if your checkout has
newer work, merge each change carefully instead of overwriting it.

## Files for the current handoff

```text
.env.example
.gitignore
README.md
app/local.py
app/products_api.py
app/data/search.py
tests/test_local_runner.py
docs/LOCAL_BACKEND_POSTMAN.md
docs/HANDOFF.md
docs/LEGACY_README.md
docs/BRANDORA_AI_COMPLETE_WALKTHROUGH.md
docs/BRANDORA_AI_TESTING_HANDBOOK.md
```

The last two files retain historical material with machine-specific paths
removed. The reusable Backend command `node dev/package-ai-handoff.cjs ../brandora-ai`
packages this explicit source/documentation allowlist and a SHA-256 manifest.
It never commits, pushes, deploys, includes Git history or reads private .env files.
Compare archive hashes against the files you intend to publish.

## Install, configure and test

Follow the [local guide](LOCAL_BACKEND_POSTMAN.md) for dependencies, virtual
environment commands, private AI configuration and canonical service startup.
AI receives the Backend public RSA key and separate service credentials.
It never needs the Backend private key, owner login/JWT or database credentials.

For offline checks, set PYTHON_DOTENV_DISABLED=1 and AI_PROVIDER=rules in a clean
local terminal; keep provider keys unset. Run the focused pytest command in the
local guide, or the full pytest suite when needed. The Backend repository owns
its separate local SQL-backed HTTP verifier and maintained Postman collection.

Observed before documentation cleanup on 2026-11-04:
- AI focused checks: 737 passed, with one dependency deprecation warning.
- Local NestJS/FastAPI/PostgreSQL: 71 assertions passed in rules mode.
- The 13 Postman requests were replayed over HTTP using Node; GUI/pm tests were not run.

These observations do not prove live Groq or production integration. New cleanup
verification is reported separately; do not infer a test run from a script's presence.

## Release limits

Preserve app.server and railway.json. Local runners bind only to loopback and
are disabled by default. Synthetic request context must never replace production
conversation persistence. Backend still needs an authorized source-message
adapter, stable history boundary/snapshot and idempotent reply persistence.
Production ingress and real end-to-end acceptance require separate verification.
Cloudinary/image matching, Orders and permanent Excel storage remain deferred.

Keep private configurations, generated keys, virtual environments, snapshots,
local databases and backups out of the handoff. Obtain separate approval before
publishing or deploying either service.
