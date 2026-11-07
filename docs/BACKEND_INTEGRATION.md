# Backend integration handoff

**Development version for local integration testing. Not production ready.**
Backend is a read-only reference; no Backend code, migration, database or deployed
configuration was changed by this AI work.

## Inspected contracts

- main and feature/product-management: 3f37c4c79f7caa5da99dc0f60f2e87f61e3d2b62.
- feature/backend-ai-integration: f7c826fc76bc0ab8569ae0ed25106ff19bdaae45.
- feature/customers-conversations: 0e92d6b5d038aa6da87c76ee5f06d29aebe4127a.

The integration branch implements OWNER-authorized AI initiation and signed
/internal/ai/data callbacks. Its production AiModule registers
UnavailableAiConversationStore. AiService.tool calls current() before every tool,
including Product reads: that unavailable store blocks them with 503 before
Product domain dispatch. Existing Product services alone cannot enable the AI.
The integration receiver is absent from inspected main; deployment is unverified.

FastAPI and the actual NestJS validator agree on exactly four response fields,
INQUIRY/PURCHASE_INTENT/OTHER and orderCandidate:null. See
[API_CONTRACT](API_CONTRACT.md) for exact JWT, request, DTO and tool bounds.
Actual source-body and mocked NestJS HTTP checks passed; real Product SQL,
persisted conversations and live Groq remain unverified.

## Conversation adapter requirements

Backend owns Customer, Conversation, Message identities, ordering and persistence.
Implement/register the existing AiConversationStore methods:

- current(businessId, conversationId, messageId): authenticate current active
  membership and tenant/customer/conversation ownership; return the immutable
  stored CUSTOMER/TEXT source, exact content and createdAt. Never trust a caller's
  customer ID or substituted message text.
- historyBefore(source, limit, offset): exclude the source timestamp and later
  messages; scope all rows, deterministic createdAt/id ordering, immutable snapshot,
  exact pagination/count and complete flag. Concurrent inserts/edits must not change
  the snapshot across pages. AI/OWNER prose never supplies catalog facts.
- saveReply(source, response): reattest source content/identity and persist once
  per source using a unique key and transaction. Reject conflicting replays;
  concurrent requests/retries must not duplicate replies or notifications.

The older Conversations branch uses Customer unique(businessId,phone), Conversation
unique(businessId,customerId,channel), OPEN/CLOSED status and CUSTOMER/AI/OWNER
senders. Message.externalMessageId is globally unique. Ingestion upserts customer
and conversation transactionally; duplicate event content/source conflicts need
explicit enforcement. Ordinary newest-first offset history with separate count
and rows is not an immutable before-source snapshot.

Reconcile the older controllers with current AuthScope/active OWNER authorization
and current Product schema. The old inbound limit is 4096 characters; canonical
AI source/history content is at most 2000 Unicode code points. Do not merge or
activate the old branch unchanged. Human review is a flag, not proof of delivery.

## Current Order draft contract — 2026-11-08

All nine visible Backend branch schemas/trees and the visible PR were inspected:
no Order/OrderItem models or Orders submission API were found. Main has transactional
InventoryService.deductForOrder/restoreForOrder helpers and order movement enums;
these are foundations, not an order service exposed through AI tools.

The existing AI extension holds one scoped OrderDraft state machine: empty,
draft, awaiting_confirmation, revalidating and blocked/cancelled. Quantity,
Product/Variant selection, missing facts and Decimal observed item subtotal are
reconstructed from authorized customer history plus fresh catalog reads.
Same-product price/variant inquiries retain quantity; corrections revoke consent.
Missing variants retain known product identity without inventing a combination.
Incomplete history discards all draft facts/confirmation. Explicit confirmation
revalidates selection; bare yes/تمام does not authorize submission.

DisabledOrderAdapter performs no I/O and always returns disabled. Data-only future
result mapping distinguishes rejection, uncertain outcome and Backend-confirmed
IDs, but no enabled adapter/runtime switch exists. No order, inventory reservation,
payment or notification is performed. Canonical responses remain null-candidate.
An observed subtotal excludes shipping/discounts and is not a durable quote.

Before enabling writes, Backend must provide an agreed versioned contract for:

1. A durable tenant/customer/conversation-scoped quote/draft ID, source binding,
   exact Product/Variant/options/quantity, authoritative prices/currency and
   explicitly defined totals, shipping and payment fields.
2. Consent bound to that quote/version, required owner approval, and transaction-time
   price/stock revalidation. Customer history reconstruction alone is not a quote.
3. Durable operation/source idempotency, atomic Order/OrderItem snapshots and stock
   changes using existing helpers; uncertain timeouts require scoped status lookup
   with the same operation key before retry.
4. Backend-issued result IDs/status, outbox/notification and payment outcomes,
   current authorization, composite tenant constraints and reviewed migrations.

submit_confirmed/lookup are proposed Python seams, not invented Backend HTTP APIs.
The AI response contract must be jointly revised before any confirmed order output.

## Shortest safe integration path

Implement the authenticated conversation adapter and correct the original Backend
cross-contract image fixture to include image.position. Supply an explicitly
verified disposable PostgreSQL environment and prepared Backend build. Run actual
Product SQL and persisted conversation/draft acceptance, including replay/race tests.
Then separately authorize live provider and protected staging/operational checks.
Orders writes remain disabled until the durable quote/submission contract exists.
No shared database, PostgreSQL installation or deployment is authorized by publishing
this development branch. Test commands and boundaries are in [TESTING](TESTING.md).
