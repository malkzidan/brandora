"""Closed-format evidence guard; no semantic approval of arbitrary model prose.

Trusted input is an EvidencePlanner-produced plan from scoped retrieval. This
guard proves presentation preserves the approved blocks, not Backend truth,
authorization, freshness or arbitrary caller-supplied plan authenticity.
"""
from dataclasses import dataclass, field
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from .evidence_planner import EvidencePlan, Resolution
from ..schemas.response import AiResponse, E03Intent


@dataclass(frozen=True)
class GroundingLimits:
    max_prompt_characters: int = 16000
    max_statements: int = 32
    max_proposal_characters: int = 4096
    max_reply_characters: int = 20000
    max_elapsed_seconds: float = 25.0

    def __post_init__(self):
        import math
        for value in (self.max_prompt_characters, self.max_statements,
                      self.max_proposal_characters, self.max_reply_characters):
            if type(value) is not int or value <= 0:
                raise ValueError("Grounding limits must be positive integers")
        if self.max_statements > 64:
            raise ValueError("Grounding statement limit exceeds presentation schema")
        if self.max_reply_characters < 128:
            raise ValueError("Reply limit must leave room for a safe generic fallback")
        if (isinstance(self.max_elapsed_seconds, bool)
                or not isinstance(self.max_elapsed_seconds, (int, float))
                or not math.isfinite(self.max_elapsed_seconds) or self.max_elapsed_seconds <= 0):
            raise ValueError("Grounding deadline must be positive and finite")


@dataclass(frozen=True)
class StatementManifest:
    ids: tuple[str, ...]
    blocks: tuple[str, ...] = field(repr=False)
    language: str


_OPENINGS = {
    "en": {"none": "", "acknowledge": "Here is the recorded information.",
           "helpful": "Let me outline the recorded information."},
    "ar": {"none": "", "acknowledge": "تمام، دي المعلومات المسجلة.",
           "helpful": "أوضحلك المعلومات المسجلة."},
}
_KINDS = frozenset({"authorization_unavailable", "scope_mismatch", "owner_review", "hard_rule", "order_policy", "help",
                    "unsupported", "business_identity", "information_unverified", "product_identity",
                    "inactive_product", "inactive_variant", "variant_observation", "clarification", "observation_limit"})
_TOOLS = frozenset({"get_products", "get_product_details", "get_product_variants", "get_variant_details", "get_business_info"})
_RECORD_PATH = re.compile(r"data(?:\.items\[\d+\])?(?:\.variants\[\d+\])?")


class InvalidEvidencePlan(ValueError):
    """Safe category only; do not include plan/customer data in the message."""


def validate_plan(plan: EvidencePlan) -> None:
    if not isinstance(plan, EvidencePlan) or plan.language not in _OPENINGS or plan.intent not in {
            E03Intent.INQUIRY, E03Intent.PURCHASE_INTENT, E03Intent.OTHER}:
        raise InvalidEvidencePlan("invalid_plan")
    if not plan.statements or not isinstance(plan.requires_review, bool):
        raise InvalidEvidencePlan("invalid_plan")
    if plan.resolution in {Resolution.AUTHORIZATION_FAILED, Resolution.SCOPE_MISMATCH} and (
            plan.products or plan.variants or plan.matching_variant_ids or plan.selected_variant_id):
        raise InvalidEvidencePlan("invalid_plan")
    products = {p.product_id: p for p in plan.products}
    variants = {v.variant_id: v for v in plan.variants}
    if len(products) != len(plan.products) or len(variants) != len(plan.variants):
        raise InvalidEvidencePlan("invalid_plan")
    if any(identifier not in variants for identifier in plan.matching_variant_ids) or (
            plan.selected_variant_id is not None and plan.selected_variant_id not in plan.matching_variant_ids):
        raise InvalidEvidencePlan("invalid_plan")
    if plan.requires_clarification and not any(s.kind in {"clarification", "information_unverified"} for s in plan.statements):
        raise InvalidEvidencePlan("invalid_plan")
    for statement in plan.statements:
        if statement.kind not in _KINDS or not statement.text.strip() or not statement.sources:
            raise InvalidEvidencePlan("invalid_plan")
        for source in statement.sources:
            valid = ((source.tool in _TOOLS and type(source.envelope_index) is int and source.envelope_index >= 0
                      and _RECORD_PATH.fullmatch(source.path) is not None)
                     or (source.tool == "application_policy" and source.envelope_index is None and source.path == "currency.EGP")
                     or (source.tool == "deterministic_template" and source.envelope_index is None and source.path == "read_only_safety"))
            if not valid:
                raise InvalidEvidencePlan("invalid_plan")
        if statement.kind in {"product_identity", "inactive_product", "inactive_variant", "variant_observation"}:
            parent = products.get(statement.product_id)
            if parent is None or parent.source not in statement.sources:
                raise InvalidEvidencePlan("invalid_plan")
        if statement.kind in {"inactive_variant", "variant_observation"}:
            variant = variants.get(statement.variant_id)
            if variant is None or variant.product_id != statement.product_id or variant.source not in statement.sources:
                raise InvalidEvidencePlan("invalid_plan")
            if statement.kind == "variant_observation" and (
                    not parent.active or not variant.parent_active or not variant.active or not variant.options_verified
                    or variant.variant_id not in plan.matching_variant_ids):
                raise InvalidEvidencePlan("invalid_plan")
    if any(v.product_id not in products for v in plan.variants):
        raise InvalidEvidencePlan("invalid_plan")
    plan.to_response()  # Existing schema and read-only intent/candidate invariant.


def compile_manifest(plan: EvidencePlan, limits: GroundingLimits) -> StatementManifest:
    validate_plan(plan)
    if len(plan.statements) > limits.max_statements:
        raise InvalidEvidencePlan("statement_limit")
    return StatementManifest(tuple(f"s{index}" for index in range(len(plan.statements))),
                             tuple(s.text for s in plan.statements), plan.language)


def deterministic_fallback(plan: EvidencePlan, limits: GroundingLimits) -> AiResponse:
    try:
        validate_plan(plan)
        response = plan.to_response()
        if len(response.reply) <= limits.max_reply_characters:
            return response
    except (ValueError, TypeError, AttributeError):
        pass
    # Broken/unbounded caller plans cannot turn their own draft into a fallback.
    ar = getattr(plan, "language", "en") == "ar"
    return AiResponse(intent=E03Intent.OTHER,
                      reply="مش قادر أتحقق من المعلومات الحالية. ممكن توضح طلبك؟" if ar else
                            "Current information could not be verified. Please clarify your request.",
                      requiresReview=bool(getattr(plan, "requires_review", False)), orderCandidate=None)


_FORBIDDEN_ACTION_CLAIMS = ('هراجع مع الفريق', 'هسأل الفريق', 'هبلغ الفريق', 'هتواصل مع الفريق', 'هراجع مع صاحب', 'هتابعه', 'تم قبول', 'اتقبل طلبك', 'تم تأكيد طلبك', 'طلبك اتأكد', 'طلبك اتسجل', 'تم تسجيل طلبك', 'تم الحجز', 'تم استلام طلبك', 'order has been accepted', 'order is confirmed', 'order confirmed', 'order has been placed', 'accepted your order', 'your order is placed', 'check with the team', "i'll check with", 'i will check with', 'will follow up', 'تم إلغاء طلبك', 'تم الغاء طلبك', 'طلبك اتلغى', 'تم تعديل طلبك', 'تم رد', 'هنرجعلك فلوسك', 'هيتم استرداد', 'تم تحويل شكواك', 'هبلغ صاحب المحل', 'هوصل شكواك', 'تم ابلاغ صاحب', 'order has been cancelled', 'order has been canceled', 'your order is cancelled', 'your order was cancelled', 'has been modified', 'has been changed', 'refund has been', 'we will refund', 'will be refunded', 'i will notify the owner', "i'll tell the owner", 'i have passed', "i've passed")


def validate_final_response(plan: EvidencePlan, response: AiResponse) -> bool:
    """Authoritative output gate for both Groq composition and Python fallback.

    Reconstruct the permitted grammar from verified facts, independently of the
    composer. Every fact stays in order, once, with every required qualifier.
    Model/provider diagnostics and the proposed reply confer no authority.
    """
    try:
        validate_plan(plan)
        response = AiResponse.model_validate(response.model_dump(mode="json"))
        if (response.intent != plan.intent or response.requiresReview != plan.requires_review
                or response.orderCandidate is not None or not response.reply.strip()
                or len(response.reply) > 20000):
            return False
        from ..nlu import normalize
        normalized = normalize(response.reply)
        # Match the start of an action phrase, not a suffix inside an unrelated
        # Arabic word (e.g. "خاتم رديوم" contains the bytes "تم رد"). Keep
        # suffix matching so action inflections remain blocked. The independent
        # closed-fact grammar below still rejects every free-prose addition.
        if any(re.search(r"(?<!\w)" + re.escape(normalize(claim)), normalized)
               for claim in _FORBIDDEN_ACTION_CLAIMS):
            return False
        # Lazy import prevents a module cycle: the grammar compiler validates
        # plans through this module, but does not authorize final responses.
        from ..chat.natural import clauses_for
        clauses, questions = clauses_for(plan)
        if not clauses:
            return response.reply == deterministic_fallback(plan, GroundingLimits()).reply
        joins = (" w ", "; ", ". ") if plan.reply_script == "franco" else (
            ("، و", "؛ ", ". ") if plan.language == "ar" else (", and ", "; ", ". "))
        separator = "(?:" + "|".join(re.escape(j) for j in joins) + ")"
        facts = separator.join(re.escape(c.text) for c in clauses)
        warmth = "tamam, " if plan.reply_script == "franco" else "تمام، " if plan.language == "ar" else "Sure, "
        prefix = "(?:" + re.escape(warmth) + ")?" if not plan.comparison else ""
        endings = [". " + " ".join(q[i] for q in questions) for i in (0,1)] if questions else [""]
        return any(re.fullmatch(prefix + facts + re.escape(end), response.reply) is not None for end in endings)
    except (ValueError, TypeError, AttributeError, KeyError):
        return False
