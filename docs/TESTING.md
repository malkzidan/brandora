# Development verification

This version is ready for local integration testing, not production deployment.
The final focused review passed 1144 tests. Run the maintained suites again in
an isolated Python 3.13 environment before integrating another Backend version:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q app tests main.py
.venv/Scripts/python.exe -m pip check
git diff --check
```

Tests use synthetic catalog/history, ephemeral signing keys and mocked providers;
no real database or Groq credentials are required. Conftest disables implicit
.env loading. No test success establishes persisted Backend or live provider
acceptance. Orders submission stays disabled and orderCandidate stays null.

Essential suites cover signed ingress, read-only tool arguments, Product DTOs,
variant/base pricing, zero versus untracked stock, history snapshots/ordering,
Arabic/English multi-turn selection, cross-request draft continuity, corrections,
cancellation, explicit confirmation, unavailable submission, tenant isolation,
provider fallback, cancellation/deadlines and the final evidence guard.

Additional safe local commands:

```powershell
.venv/Scripts/python.exe -X utf8 -m app.offline_demo --evaluate
.venv/Scripts/python.exe -X utf8 -m tests.http_smoke
.venv/Scripts/python.exe -X utf8 -m tests.release_smoke
.venv/Scripts/python.exe -m tests.export_contract
```

The HTTP smoke test starts/stops loopback synthetic servers. The release smoke
uses ephemeral configuration to check the same production launcher locally;
it never deploys. Exported schemas are review aids, not a second contract.

Optional read-only cross-repository checks require an operator-prepared temporary
source snapshot from Backend integration commit
f7c826fc76bc0ab8569ae0ed25106ff19bdaae45:

```powershell
node tests/backend_cross_contract.cjs --backend-reference <snapshot> --python .venv/Scripts/python.exe
node tests/nest_workflow.cjs --backend-reference <snapshot> --dependencies <test-dependencies> --python .venv/Scripts/python.exe
```

Both runners verify Git blob hashes. The first runs actual signing/presenter/
validator bodies with the unchanged Backend Python harness. It requires Node
with built-in stripTypeScriptTypes. The second runs actual NestJS/FastAPI HTTP
with explicitly mocked Product services, owner/session records and conversation
storage. Its reusable source manifest is retained under docs/verification.
Optional Node dependencies: typescript@5.9, @nestjs/common/core/platform-express/
jwt@11, @nestjs/config@4, class-validator@0.14, class-transformer@0.5,
reflect-metadata@0.2 and rxjs@7. Install them only in an isolated test directory.
Neither check proves Prisma queries, database persistence or production AppModule.

Real PostgreSQL acceptance is blocked until a verified disposable database and
a real authenticated conversation adapter are supplied. Live Groq and protected
staging/deployment acceptance require separate authorization. Never use shared,
Neon, Railway, staging or production databases for these tests.

Generated console/XML traces, machine-local paths, Git status dumps and historical
audit reports remain local and are excluded from the development commit.
