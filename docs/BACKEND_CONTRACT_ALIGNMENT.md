# Local Backend contract alignment (2026-11-05)

This supplements FINAL_BACKEND_AI_HANDOFF.md; it does not activate integration.

- History includes only rows strictly earlier than beforeMessageCreatedAt.
  Exclude every row at the current message timestamp, regardless of UUID.
- Sort earlier rows by createdAt DESC, then canonical UUID DESC. This is
  deterministic pagination, not evidence of causal ordering. Two CUSTOMER rows
  sharing a timestamp are ambiguous and must not reconstruct selectors.
- Every non-null internal history content has a 2000-Unicode-code-point maximum,
  matching current messages. Blank/non-TEXT customer rows remain unusable for
  reconstruction. Oversized history is rejected, never silently truncated;
  unavailable/partial history produces clarification, never guessed context.
  Backend's future adapter must attest ties across pages and immutable snapshots.
- AI's total integration deadline must be positive and at most 25 seconds.
  Backend's HTTPS deadline is 30 seconds, leaving five seconds for transport and
  serialization. Backend callbacks retain a five-second per-call timeout; store
  adapters must separately bound SQL/persistence operations.
- Five-field request, exact-byte hash, RS256, independent service credentials,
  scoped Product/Variant tools and null orderCandidate are unchanged.
- get_business_info remains a Backend-only extension, outside canonical AI tools.
  Optional image metadata remains ignored; catalogItemId stays the Variant wire
  alias until a separately coordinated contract change. No image write tools.
- No real Conversation Store exists in Backend main. Integration remains disabled.
  The upcoming Backend release excludes the local AI integration entirely; Malak
  reviews/publishes this repository independently. No live acceptance is claimed.
