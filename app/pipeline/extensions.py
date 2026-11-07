"""Disabled, data-only seam for a future Backend-owned order workflow.

No order client, handler, dispatch, configuration switch or inventory operation
exists here. A handoff is customer intent, never an authorized order command.
"""
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Literal

from ..schemas.response import E03Intent
from .evidence_planner import CandidateReference, EvidencePlan, Resolution


@dataclass(frozen=True)
class ProvisionalPurchaseIntent:
    references: tuple[CandidateReference, ...] = field(repr=False)
    requested_quantity: int | None = field(repr=False)
    requested_options: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    missing_selections: tuple[str, ...] = ()
    confirmation_required: bool = True


@dataclass(frozen=True)
class DisabledOrderExtension:
    enabled: Literal[False] = field(default=False, init=False)
    purchase_intent: ProvisionalPurchaseIntent | None = field(default=None, repr=False)
    draft: 'OrderDraft | None' = field(default=None, repr=False)


class OrderState(str, Enum):
    EMPTY = 'empty'
    DRAFT = 'draft'
    AWAITING_CONFIRMATION = 'awaiting_confirmation'
    REVALIDATING = 'revalidating'
    BLOCKED = 'blocked'
    CANCELLED = 'cancelled'
    UNCERTAIN = 'uncertain'
    SUBMITTED = 'submitted'


@dataclass(frozen=True)
class OrderDraft:
    """Request-local intent, reconstructed only from authorized customer history.

    Observed subtotal excludes shipping/discount/payment. Never an order candidate,
    reservation, durable quote or authorization to write.
    """
    state: OrderState = OrderState.EMPTY
    scope: tuple[str, ...] = field(default=(), repr=False)
    product_id: str | None = None
    variant_id: str | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    subtotal: Decimal | None = None
    options: tuple[tuple[str, str], ...] = ()
    missing: tuple[str, ...] = ()
    fingerprint: str | None = None
    source_message_id: str | None = None
    confirmed_by_message_id: str | None = None
    backend_order_id: str | None = None
    reason: str | None = None


class SubmissionStatus(str, Enum):
    DISABLED = 'disabled'
    REJECTED = 'rejected'
    UNCERTAIN = 'uncertain'
    CONFIRMED = 'confirmed'


@dataclass(frozen=True)
class OrderSubmissionResult:
    status: SubmissionStatus
    backend_order_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.status, SubmissionStatus):
            raise ValueError('Invalid submission status')
        if (self.status == SubmissionStatus.CONFIRMED) != bool(self.backend_order_id):
            raise ValueError('Only a verified Backend confirmation may carry an order ID')


class DisabledOrderAdapter:
    """Proposed adapter seam, not a fabricated HTTP API or writable tool.

    A future implementation needs a Backend-issued quote/version, scoped approval,
    durable idempotency and status lookup. None is available in today's contract.
    """
    def submit_confirmed(self, draft: OrderDraft) -> OrderSubmissionResult:
        return OrderSubmissionResult(SubmissionStatus.DISABLED)

    def lookup(self, scope, idempotency_key) -> OrderSubmissionResult:
        return OrderSubmissionResult(SubmissionStatus.DISABLED)


def is_order_confirmation(text):
    from ..nlu import normalize
    value=normalize(text).strip(' .!؟?')
    return value in {'confirm order', 'confirm the order', 'yes confirm order',
                     'اكد الطلب', 'اكدي الطلب', 'ايوه اكد الطلب', 'اوافق علي الطلب'}


def draft_from_plan(plan, scope, message_id):
    matches=[v for v in plan.variants if v.variant_id in plan.matching_variant_ids
             and v.active and v.parent_active and v.options_verified]
    missing=list(plan.missing_facts)+list(plan.ambiguities)
    if len(plan.products)!=1 or len(matches)!=1:missing.append('unique_product_variant')
    v=matches[0] if len(plan.products)==len(matches)==1 else None
    q=plan.requested_quantity
    if q is None:missing.append('quantity')
    if v is None or v.effective_price is None:missing.append('price')
    if v is None or v.recorded_quantity is None:missing.append('authoritative_availability')
    elif q is not None and q>v.recorded_quantity:missing.append('sufficient_stock')
    if plan.requires_review:missing.append('human_review')
    if set(plan.limitations)-{'recorded_observations_not_reservations','no_stable_snapshot'}:
        missing.append('complete_evidence')
    keys=tuple(str(x) for x in (scope.business_id,scope.customer_id,scope.conversation_id))
    price=v.effective_price if v else None
    options=v.option_values if v else ()
    product_id=str(plan.products[0].product_id) if len(plan.products)==1 else None
    payload=[keys,product_id,str(v.variant_id) if v else None,q,str(price),options]
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    return OrderDraft(OrderState.DRAFT if missing else OrderState.AWAITING_CONFIRMATION,
                      keys,product_id,str(v.variant_id) if v else None,q,price,
                      price*q if price is not None and q is not None else None,options,
                      tuple(dict.fromkeys(missing)),fingerprint,str(message_id))


def confirm_draft(previous, fresh, message_id):
    """Revalidation never converts changed/incomplete intent into submission."""
    if previous.scope != fresh.scope:
        raise ValueError('Order scope mismatch')
    if previous.state != OrderState.AWAITING_CONFIRMATION:
        return replace(fresh,reason='no_confirmable_draft')
    if fresh.missing or fresh.fingerprint!=previous.fingerprint:
        return replace(fresh,reason='draft_changed_reconfirm')
    revalidated=replace(fresh,state=OrderState.REVALIDATING,confirmed_by_message_id=str(message_id))
    return apply_submission_result(revalidated,DisabledOrderAdapter().submit_confirmed(revalidated))


def apply_submission_result(draft, result):
    if draft.state!=OrderState.REVALIDATING or not draft.confirmed_by_message_id:
        raise ValueError('Submission requires explicit confirmation and revalidation')
    if result.status==SubmissionStatus.CONFIRMED:
        return replace(draft,state=OrderState.SUBMITTED,backend_order_id=result.backend_order_id,reason=None)
    state=OrderState.UNCERTAIN if result.status==SubmissionStatus.UNCERTAIN else OrderState.BLOCKED
    return replace(draft,state=state,reason={SubmissionStatus.DISABLED:'backend_orders_unavailable',
                   SubmissionStatus.REJECTED:'backend_rejected',SubmissionStatus.UNCERTAIN:'lookup_before_retry'}[result.status])


def reserve_order_extension(plan: EvidencePlan, requested_options=None) -> DisabledOrderExtension:
    """Retain minimal intent metadata without executing or enabling anything.

    Even references checked by current read-only retrieval require new authorized,
    transaction-time Backend validation for any eventual order operation.
    """
    if plan.intent != E03Intent.PURCHASE_INTENT or plan.resolution in {
            Resolution.AUTHORIZATION_FAILED, Resolution.SCOPE_MISMATCH, Resolution.INVALID,
            Resolution.UNAVAILABLE, Resolution.UNSUPPORTED} or "retrieval_inquiry_mismatch" in plan.limitations:
        return DisabledOrderExtension()
    references = list(plan.references)
    references.extend(CandidateReference(v.product_id, v.variant_id, "planning", False)
                      for v in plan.variants if v.variant_id in plan.matching_variant_ids)
    unique = {}
    for reference in references:
        key = (reference.product_id, reference.variant_id)
        unique.setdefault(key, replace(reference, revalidated=False))
    missing = list(plan.missing_facts) + list(plan.ambiguities)
    if not plan.matching_variant_ids or len(plan.matching_variant_ids) != 1:
        missing.append("unique_variant")
    if plan.requested_quantity is None:
        missing.append("quantity")
    return DisabledOrderExtension(ProvisionalPurchaseIntent(
        tuple(unique.values()), plan.requested_quantity, tuple((requested_options or {}).items()),
        tuple(dict.fromkeys(missing))))
