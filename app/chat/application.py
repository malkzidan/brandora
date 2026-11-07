"""Session-owned conversational composition over the existing standalone stack."""
import asyncio
from dataclasses import asdict, dataclass, field, replace
from uuid import uuid4

from ..data.options import resolve_options
from ..data.retrieval import RetrievalDecision
from ..nlu import extract_entities
from ..pipeline.standalone import StandalonePipeline, StandaloneExecutionResult
from ..pipeline.evidence_planner import EvidencePlanner, Resolution, GroundedStatement, EvidenceSource
from ..schemas.response import E03Intent, ReviewReason
from ..pipeline.price_comparison import compare_verified_pair
from ..schemas.backend import InventoryState
from ..schemas.backend import ExpectedScope
from .understanding import ConversationInterpreter, Selection, Understood, declines_selection, asks_stock_quantity
from ..pipeline.extensions import (OrderDraft, OrderState, draft_from_plan,
                                   confirm_draft, is_order_confirmation)


@dataclass(frozen=True)
class ChatTurn:
    execution: StandaloneExecutionResult = field(repr=False)
    understanding: Understood = field(repr=False)
    tools: tuple[str, ...]

    @property
    def response(self):
        return self.execution.response

    def diagnostics(self):
        e = self.execution
        return {"intent": self.response.intent.value, "understanding": self.understanding.source,
                "understandingProvider": self.understanding.source.split("_")[0],
                "replyProvider": (e.diagnostics.generation_source.split("_")[0]
                                  if e.diagnostics.generation_source in {"groq_conversation"} else "deterministic"),
                "tools": self.tools, "candidates": [p.name for p in e.retrieval.candidates],
                "matchingVariants": [str(v) for v in e.plan.matching_variant_ids],
                "selectedVariant": str(e.plan.selected_variant_id) if e.plan.selected_variant_id else None,
                "clarification": e.plan.requires_clarification, "resolution": e.plan.resolution.value,
                "fallback": self.understanding.fallback or e.diagnostics.fallback_reason,
                "understandingFailure": self.understanding.fallback,
                "replyFailure": e.diagnostics.fallback_reason,
                "providerFailures": {
                    "understanding": [asdict(d) for d in self.understanding.provider_diagnostics],
                    "reply": [asdict(d) for d in e.generation.provider_diagnostics]},
                "source": e.diagnostics.generation_source, "ordersEnabled": False,
                "backendCalls": e.diagnostics.backend_calls,
                "understandingMs": self.understanding.elapsed_ms,
                "executionMs": e.diagnostics.elapsed_ms,
                "elapsedMs": e.diagnostics.elapsed_ms + self.understanding.elapsed_ms,
                "quantity": e.plan.requested_quantity}


class ChatSession:
    """One explicitly scoped conversation. Serialize its turns; no global registry.

    This local caller establishes scope, not authentication. A production caller
    must authenticate scope and persist/version these hints server-side. No raw
    historical assistant prose, prices or stock are used to prepare a follow-up.
    """
    def __init__(self, data, scope: ExpectedScope, interpreter: ConversationInterpreter, responder, *,
                 initial_selection=None,repeat_current_price=False,initial_order=None,initial_order_query=None):
        self.scope, self.interpreter = scope, interpreter
        self._data, self._responder = data, responder
        self.selection = initial_selection or Selection()
        self._repeat_current_price=repeat_current_price
        if initial_order is not None and initial_order.scope and initial_order.scope != tuple(
                str(v) for v in (scope.business_id,scope.customer_id,scope.conversation_id)):
            raise ValueError('Order scope mismatch')
        self.order_draft=initial_order or OrderDraft()
        self.order_query=initial_order_query
        self._lock = asyncio.Lock()

    async def reset(self):
        async with self._lock:
            self.selection = Selection()
            self.order_draft=OrderDraft()
            self.order_query=None

    async def send(self, text: str, *, context_token: str, message_id=None,prepared_understanding=None) -> ChatTurn:
        async with self._lock:
            understood = prepared_understanding or await self.interpreter.understand(text, self.selection)
            confirmation=is_order_confirmation(text)
            if (confirmation and prepared_understanding is None and self.order_query is not None
                    and self.order_draft.state==OrderState.AWAITING_CONFIRMATION):
                # The saved query contains selectors only. The normal pipeline
                # fetches fresh Product/Variant evidence under this turn's token.
                understood=self.order_query
            pipeline = StandalonePipeline(self._data, self._responder, planner=ConversationPlanner(
                understood,self.selection,repeat_current_price=self._repeat_current_price,
                order_confirmation=confirmation,
                allow_stock_quantity_disclosure=(asks_stock_quantity(text) and
                    str(self.scope.business_id) in self.interpreter.settings.stock_quantity_disclosure_businesses)))
            execution = await pipeline.execute(understood.inquiry, scope=self.scope,
                message_id=message_id or uuid4(), context_token=context_token, prepare_history=False)
            if declines_selection(text):
                self.order_draft=OrderDraft(state=OrderState.CANCELLED,reason='local_draft_cancelled')
                self.order_query=None
            elif execution.retrieval.failure is not None or prepared_understanding is not None:
                self.order_draft=OrderDraft(state=OrderState.BLOCKED,reason='evidence_unavailable')
                self.order_query=None
            elif execution.plan.intent==E03Intent.PURCHASE_INTENT:
                fresh=draft_from_plan(execution.plan,self.scope,execution.binding.message_id)
                self.order_draft=confirm_draft(self.order_draft,fresh,execution.binding.message_id) if confirmation else fresh
                self.order_query=understood
            elif (self.order_draft.state in {OrderState.DRAFT,OrderState.AWAITING_CONFIRMATION}
                  and understood.meaning.act in {'price','product'} and not execution.plan.requires_review
                  and len(execution.plan.products)==1
                  and str(execution.plan.products[0].product_id)==self.order_draft.product_id):
                # An inquiry about the same product is not abandonment. Refresh
                # the draft (including corrected options) without turning this
                # inquiry's response into a new purchase or confirmation.
                fresh=draft_from_plan(replace(execution.plan,requested_quantity=self.order_draft.quantity),
                                      self.scope,execution.binding.message_id)
                self.order_draft=fresh
                self.order_query=replace(understood,
                    meaning=understood.meaning.model_copy(update={'act':'purchase','quantity':fresh.quantity}),
                    inquiry=understood.inquiry.model_copy(update={
                        'text':f'I want to buy product quantity {fresh.quantity}' if fresh.quantity is not None else 'I want to buy product',
                        'product_ids':(execution.plan.products[0].product_id,)}))
            elif confirmation:
                self.order_draft=OrderDraft(state=OrderState.BLOCKED,reason='no_confirmable_draft')
                self.order_query=None
            elif execution.retrieval.candidates or understood.meaning.act!='other' or execution.plan.requires_review:
                # Inquiry/product switches invalidate an earlier confirmation.
                self.order_draft=OrderDraft()
                self.order_query=None
            execution=replace(execution,order_extension=replace(execution.order_extension,draft=self.order_draft))
            # Intent, language and quantity are semantic customer requests, not
            # Backend facts. Keep the planner's safety decisions authoritative.
            # Quantity extraction from canonical text is checked by regression tests.
            if execution.retrieval.failure is not None:
                self.selection = Selection()
            elif execution.retrieval.candidates:
                products = tuple(p.model_copy(deep=True) for p in execution.retrieval.candidates)
                options = ()
                if len(products) == 1:
                    options = resolve_options(products[0], understood.inquiry.text,
                                              understood.inquiry.option_values).values
                alternatives=(tuple((key,tuple(values)) for key,values in understood.inquiry.option_alternatives.items())
                              if understood.meaning.act=="compare" else ())
                quantity=understood.meaning.quantity
                if (self.order_draft.state in {OrderState.DRAFT,OrderState.AWAITING_CONFIRMATION}
                        and len(products)==1 and str(products[0].id)==self.order_draft.product_id):
                    quantity=self.order_draft.quantity
                self.selection = Selection(products, options, quantity,alternatives)
            elif understood.meaning.act != "other":
                self.selection = Selection()
            elif declines_selection(text):
                self.selection = Selection()
            elif (execution.retrieval.decision == RetrievalDecision.CLARIFY
                  and extract_entities(text).product_tokens):
                # An unresolved new topic must not leave an old purchase ready
                # for an accidental subsequent "one of it" reference.
                self.selection = Selection()
            tools = tuple(dict.fromkeys(out.envelope.tool for out in execution.retrieval.evidence if out.envelope))
            return ChatTurn(execution, understood, tools)


class ConversationPlanner(EvidencePlanner):
    """Per-turn language/quantity from interpretation, facts from the base planner."""
    def __init__(self, understood, previous=None, *, repeat_current_price=False,allow_stock_quantity_disclosure=False,order_confirmation=False):
        self._meaning = understood.meaning
        self._previous = previous or Selection()
        self._repeat_current_price=repeat_current_price
        self._allow_stock_quantity_disclosure=allow_stock_quantity_disclosure
        self._order_confirmation=order_confirmation

    def plan(self, inquiry, result, history=None):
        plan = super().plan(inquiry, result, history)
        if declines_selection(inquiry.text):
            reply = ("تمام، نسيب الاختيار ده. تحب تشوف حاجة تانية؟" if self._meaning.language == "ar"
                     else "Okay, we'll leave that option. Would you like to look at something else?")
            return replace(plan, intent=E03Intent.OTHER, language=self._meaning.language,
                           resolution=Resolution.SIMPLE_RESPONSE, requires_clarification=False,
                           requested_quantity=None, statements=(GroundedStatement("hard_rule", reply,
                               (EvidenceSource("deterministic_template", None, "read_only_safety"),)),))
        if self._meaning.act == "other":
            if self._order_confirmation:
                notice=('مفيش مسودة مكتملة للتأكيد، وإنشاء الطلبات مش متاح حاليًا. ممكن تحدد المنتج والمقاس والكمية؟'
                        if plan.language=='ar' else 'There is no complete draft to confirm. Order submission is unavailable. Which product, variant and quantity?')
                return replace(plan,resolution=Resolution.SIMPLE_RESPONSE,requires_clarification=False,
                               statements=(GroundedStatement('order_policy',notice,
                                (EvidenceSource('deterministic_template',None,'read_only_safety'),)),))
            return plan
        plan = replace(plan, language=self._meaning.language, requested_quantity=self._meaning.quantity,
                       allow_stock_quantity_disclosure=self._allow_stock_quantity_disclosure,
                       comparison_metric=self._meaning.comparison_metric,
                       comparison_alternatives=tuple((key,tuple(values)) for key,values in inquiry.option_alternatives.items()),
                       comparison=self._meaning.act == "compare",reply_script=self._meaning.script,
                       reply_focus=("comparison" if self._meaning.act == "compare" else
                           "purchase" if self._meaning.act == "purchase" else "price" if self._meaning.act == "price" and self._meaning.focus == "discovery"
                           else self._meaning.focus))
        if self._meaning.act == "purchase" and self._meaning.product_handle is not None:
            previous_prices = {v.id:v.effectivePrice for p in self._previous.products for v in p.variants}
            # Earlier observations only determine whether a changed price needs
            # disclosing. All quoted values still come from the fresh plan.
            changed = any(previous_prices.get(v.variant_id) != v.effective_price for v in plan.variants
                          if v.variant_id in plan.matching_variant_ids)
            selections_changed = dict(inquiry.option_values) != dict(self._previous.options)
            plan = replace(plan,show_price=changed or selections_changed or self._repeat_current_price)
        if (plan.resolution == Resolution.SINGLE_VARIANT and not plan.missing_facts
                and not plan.ambiguities and not set(plan.limitations) - {
                    "recorded_observations_not_reservations", "no_stable_snapshot"} and not result.failure):
            variant = next(v for v in plan.variants if v.variant_id in plan.matching_variant_ids)
            # A complete read-only purchase enquiry doesn't need the legacy
            # generic clarification. Selection remains distinct from an order.
            selected = variant.variant_id if variant.inventory == InventoryState.RECORDED_POSITIVE else None
            plan = replace(plan, requires_clarification=False, selected_variant_id=selected)
        if compare_verified_pair(plan) is not None:
            plan = replace(plan,requires_clarification=False,selected_variant_id=None)
        matches=[v for v in plan.variants if v.variant_id in plan.matching_variant_ids]
        if (plan.intent==E03Intent.PURCHASE_INTENT and plan.resolution==Resolution.SINGLE_VARIANT
                and len(plan.products)==len(matches)==1 and not plan.ambiguities and not result.failure
                and not set(plan.limitations)-{"recorded_observations_not_reservations","no_stable_snapshot"}):
            variant=matches[0]
            if (variant.active and variant.parent_active and variant.options_verified
                    and variant.recorded_quantity is not None and plan.requested_quantity is not None
                    and plan.requested_quantity>variant.recorded_quantity):
                plan=replace(plan,requires_review=True,review_reason=ReviewReason.OUT_OF_STOCK_RISK)
        if self._order_confirmation:
            notice=('إنشاء الطلبات مش متاح حاليًا؛ مفيش طلب اتعمل ولا حجز مخزون أو دفع.'
                    if plan.language=='ar' else
                    'Order submission is unavailable. No order, inventory reservation or payment was made.')
            plan=replace(plan,statements=plan.statements+(GroundedStatement('order_policy',notice,
                (EvidenceSource('deterministic_template',None,'read_only_safety'),)),))
        elif (plan.intent==E03Intent.PURCHASE_INTENT and not plan.requires_review
              and len(plan.products)==len(matches)==1 and plan.requested_quantity is not None
              and not plan.missing_facts and not plan.ambiguities
              and matches[0].effective_price is not None and matches[0].recorded_quantity is not None
              and 0<plan.requested_quantity<=matches[0].recorded_quantity):
            notice=('دي مسودة اختيار بس، مش طلب منفذ. لو موافق على الاختيار قول «أكد الطلب»؛ إنشاء الطلبات لسه غير متاح.'
                    if plan.language=='ar' else 'This is a selection draft only. Say "confirm order" to confirm the selection; order submission remains unavailable.')
            plan=replace(plan,statements=plan.statements+(GroundedStatement('order_policy',notice,
                (EvidenceSource('deterministic_template',None,'read_only_safety'),)),))
        return plan
