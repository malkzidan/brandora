# Unified engine

Current addition (2026-11-08): the existing `pipeline/extensions.py` now holds the
single OrderDraft state model and disabled adapter. `ChatSession` derives draft
state from fresh evidence; authorized customer-history replay reconstructs intent
through that same session implementation. Explicit confirmation causes fresh reads,
then a blocked outcome, never CONFIRMED_ORDER. `ConversationPlanner` supplies
closed policy clauses and `NaturalResponder`/the final guard render/check them.
No new route, tool, client or persistent/global conversation registry was added.
Same-product inquiries refresh the reconstructed draft without discarding its
quantity. Missing combinations retain only the known product identity, not an
invented variant. Incomplete authorized history discards all reconstructed draft
facts and confirmation; no global cache compensates for missing history.
Legacy E0-3 candidate schemas remain compatibility types, unreachable from the
canonical null-candidate response. Future `submitted`/`uncertain` result mapping is
data-only; the only concrete adapter returns disabled and does no I/O.

## Workflow ownership and failure boundaries

| Stage / owner | Input → output | Tool/auth boundary | Failure behavior / evidence |
|---|---|---|---|
| Backend initiation | owner session + stored source IDs → exact five-field request | AuthGuard active OWNER, current source, short-lived RS256 context and raw-body hash | Reject unauthorized/changed source; actual HTTP Level 4 |
| AI ingress | signed bytes → validated request scope | Directional credential, exact claims/lifetime, body binding, payload bound | Fail closed; security suite + Level 4 |
| Canonical understanding | current message → act/options/quantity | Rules or bounded provider; no catalog authority | Deterministic fallback; workflow tests |
| Authorized context | dependent follow-up → intent references | get_conversation_history with signed source scope and immutable snapshot | Clarify if unavailable/invalid; no stale factual inheritance |
| Retrieval | discovery/exact selection → typed catalog evidence | get_products, get_product_details, get_product_variants, get_variant_details; Backend reattests current source on every call | Reject malformed/foreign/inactive facts; paginate within bounds; Levels 2–4 |
| Evidence planning | typed current evidence + intent → price/stock/comparison/shortfall plan | Provenance, effective variant price, stock policy; no model facts | Missing price/combo or ambiguity stays unresolved; offline suites |
| Generation + guard | protected plan → strict four-field response | Rules or Groq wording; final evidence guard | Reject unsupported claims, deterministic safe reply; orderCandidate null |
| Backend completion | validated response → persisted reply | Reattest source; saveReply idempotency | Production adapter unavailable; mock boundary verified, SQL BLOCKED |

`tests/workflow_probe.py` observes the canonical engine only inside tests. It is
not imported by production and introduces no second engine or data fallback.
The optional Nest test uses unchanged pinned Backend sources and explicit mocked
adapters, never Prisma. See the latest report for execution-level limits.

`app.http.create_app` is the sole FastAPI factory. `python -m app.server` is the
release launcher; `main:app` is an ASGI import of that same factory.

```text
Backend request → ingress limits → service token + RS256 context + raw-body hash
→ api.ConversationRequest → conversation_api.execute_conversation
→ authorized history only if needed → replay CUSTOMER selectors
→ ChatSession → ConversationInterpreter → StandalonePipeline
→ RetrievalCoordinator → BackendDataAccess → BackendClient
→ typed Product/Variant evidence → ConversationPlanner/EvidencePlanner
→ NaturalResponder → evidence_guard.validate_final_response → AiResponse
```

Python authorizes every tool, binds scope and budgets, resolves actual option
combinations, applies review/disclosure policies and validates output. Groq
interprets structured intent/selectors and groups approved fact clauses into
natural sentences. It receives no credentials, authorization identities or
historical prices. It never chooses URLs or executes HTTP tools.

Groq timeout, malformed JSON, unavailable models and rejected proposals fall
back to deterministic Python through the same composer and final guard. A
release requires Groq configuration; runtime outages still have safe fallback.
Closed composition forbids arbitrary factual prose: every fact appears once,
in order, with its qualifiers. The final guard independently reconstructs that
grammar, checks response fields and rejects legacy forbidden action claims.

V1 contributes Egyptian Arabic normalization, entity/intent extraction, human
review taxonomy and forbidden-action policy. V2 contributes signed scope,
bounded typed retrieval, authorized history, variant semantics and natural
composition. The old supplied-catalog planner, prose generator, order confirmation
engine and Gemini/OpenRouter implementations are removed. Capability decisions
are protected by the essential regression suites described in [TESTING](TESTING.md).

History reconstruction is request-local. Only CUSTOMER selectors are replayed;
AI/OWNER prose never supplies product facts. Current reads refresh prices and
stock. Missing, partial, tied or inconsistent snapshots cause clarification.
No persistent AI conversation store or exactly-once delivery cache exists.
Backend owns persistence, ordering, snapshots and message idempotency.
The Backend integration branch `f7c826f` implements S2S routes, signing and
read-only dispatch. Its registered UnavailableAiConversationStore intentionally
blocks real source-turn/history/reply persistence; an implemented transport
does not imply production conversation availability. The audited signing profile
uses a 60-second lifetime and no nbf/kid extensions.

`requiresReview` flags human review; it does not send a notification. Quantity
shortfall on a verified single variant raises OUT_OF_STOCK_RISK. Stock counts
are disclosed only after an explicit customer question and an operator-owned
business allowlist. Untracked stock remains unknown. Every orderCandidate is
null; no order, inventory, image or product write tool is reachable.

The synthetic harness is imported only by explicit development/test commands.
Both its HTTP requests and the local real-client runner use the canonical app.
