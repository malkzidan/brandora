# Canonical API and Backend integration-branch tools v1

Verified against `feature/backend-ai-integration` at
`f7c826fc76bc0ab8569ae0ed25106ff19bdaae45` on 2026-11-07. The receiver is
implemented on that branch, absent from `main`, and not verified deployed.

Only conversation route: `POST /v2/ai/respond`. Removed routes return 404:
`/v1/ai/respond`, `/v2/ai/products/respond`, `/v2/ai/respond-with-context`.
There is no verified consumer requiring a compatibility contract.

Request JSON has exactly businessId, customerId, conversationId, messageId
(canonical UUIDs) and message (nonblank string, at most 2000 Unicode code points).
The request never accepts catalog or history. Response has exactly intent
(INQUIRY/PURCHASE_INTENT/OTHER), reply, requiresReview and orderCandidate=null.
The canonical output validator rejects CONFIRMED_ORDER, empty/oversize replies
and responses above 65536 UTF-8 bytes.

## Authentication

Headers: Content-Type application/json, X-Internal-Token (Backend→AI secret),
X-AI-Context (RS256 JWT). Verify an RSA public key of at least 2048 bits. JWT
header contains exactly alg=RS256 and typ=JWT. Claims forbid extras and require:

| Claim | Required value |
|---|---|
| iss | brandora-backend |
| aud | brandora-ai-tools-v1 |
| scope | products:read conversations:read |
| businessId/customerId/conversationId/messageId | Exact request identities |
| requestHash | Lowercase SHA256 hex of the exact raw request-body bytes |
| iat, exp | Integer timestamps; 0 ≤ iat ≤ now < exp ≤ iat + 60; no clock skew |

`nbf`, `kid` and other extensions are not part of this branch's signed contract;
AI rejects them rather than forwarding contexts the Backend would reject.

Service credentials are separate inbound/outbound values, 32–4096 printable
non-whitespace ASCII characters. OWNER access tokens are never service secrets.
Release requests require HTTPS. Forwarded HTTPS is trusted only from an explicitly
configured immediate socket peer; wildcard proxy trust is rejected.

## Implemented tool transport on feature/backend-ai-integration

AI sends POST `/internal/ai/data` with Authorization: Bearer BACKEND_SERVICE_TOKEN
and X-AI-Context, forwarding the verified per-request JWT. JSON is
`{"tool":"get_products","arguments":{"limit":20,"offset":0}}`.
The v1 contract is identified by the JWT audience; response header
X-AI-Contract is conversation-tools-v1. Tool arguments never authorize businessId.
Backend's AiInternalGuard verifies service identity and signed context. AiService
re-attests the current source turn, customer and original body hash before each
tool; domain services enforce nested product/business scope. The requestHash
binds the original AI request, not each tool POST body. The dispatcher separately
validates tool arguments. All store-dependent operations currently fail closed
through UnavailableAiConversationStore.

| Tool | Arguments | Success data |
|---|---|---|
| get_products | limit, offset | items Product[], pagination |
| get_product_details | productId | Product |
| get_product_variants | productId, limit, offset | items ProductVariant[], pagination |
| get_variant_details | productId, variantId | ProductVariant |
| get_conversation_history | conversationId, limit, offset | AuthorizedHistoryPage |

Backend additionally dispatches `get_business_info` to profile/settings/hours.
It remains deliberately excluded from the canonical AI allowlist; this audit
does not enable policy/hours capabilities or add a replacement endpoint.

Success envelope is `{tool, data}`. Pagination has limit (1..100, default 20),
offset (default 0), totalCount, hasMore, nextOffset. Integers must be nonnegative
JavaScript-safe integers; continuation must progress and match requested bounds.
Identifiers use canonical UUID strings. Authoritative parsers are
`app/schemas/backend.py`; tool argument/envelope validation is in
`app/clients/backend_client.py`; claims/request validation is in `app/api.py`.
Generated [schema snapshot](verification/contract-schemas.json) is review material,
not an independently edited contract. Regenerate when these models change.

AuthorizedHistoryPage additionally requires businessId, customerId, conversationId,
beforeMessageId, beforeMessageCreatedAt, snapshot, order=createdAt_desc_id_desc,
complete, pagination and items. Rows require id, conversationId, senderType
(CUSTOMER/AI/OWNER), content (null or ≤2000 code points), messageType, createdAt;
externalMessageId is optional. Exclude all rows at/after the current timestamp.
Stable snapshots and boundaries must agree across pages; equal-timestamp customer
messages are ambiguous, not a causal ordering inferred from UUIDs. No silent
truncation or trusting historical assistant claims is permitted.

Backend errors should use its existing `{statusCode,code,message,error}` envelope.
AI does not forward upstream error prose. Backend 401/403 becomes canonical 403;
404/5xx/timeout/malformed data yield a grounded unavailable/clarification reply,
never fabricated successful retrieval. Overall deadline exhaustion returns 503.
Ingress authentication failures return 401, binding mismatch 403, invalid JSON
shape 400, oversize body 413, body-read timeout 408, capacity exhaustion 429.

## Bounds

Ingress: 65536 bytes / 10 seconds. Canonical execution: at most 25 seconds.
Default Backend call: 5 seconds; no automatic retries or redirects; environment
proxies disabled. Backend response: ≤128 KiB decompressed, matching AiService's
serialized envelope limit. Groq response: ≤256 KiB.
Request-local Backend budget: 12 calls shared by history replay/current turn.
History: at most 3 pages, 60 messages, 12000 characters, 5 seconds. Retrieval
has additional page/candidate/time bounds and never treats partial pages as
proof of absence. There are at most 64 active inference executions per process;
this capacity limit is not a distributed per-client rate limiter. Backend/ingress
must own deployment-wide quotas and abuse protection.
