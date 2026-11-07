"""Shared current-turn routing for standalone retrieval and evidence planning.

Reuse the legacy classifier; keep its existing standalone safety overrides in
one place. The same routing policy is used by the canonical engine and Python fallback.
"""
import re

from ..nlu import RuleContext, classify_rules, normalize
from ..schemas import Intent, OWNER_REVIEW_INTENTS, RouterResult


def route_current_inquiry(text: str) -> RouterResult:
    result = classify_rules(text, RuleContext())
    intent = result.intents[0] if result.intents else Intent.UNKNOWN
    normalized = normalize(text)
    if normalized in {"how do i use this bot", "how does this bot work"}:
        result.intents = [Intent.HELP]
    elif normalized in {"i have a complaint", normalize("عندي شكوى")}:
        result.intents = [Intent.COMPLAINT]
    elif intent not in OWNER_REVIEW_INTENTS and re.search(
            r"\b(?:order|delivery)\b.*\b(?:late|delayed|wrong|damaged|never arrived)\b", normalized):
        result.intents = [Intent.COMPLAINT]
    elif intent == Intent.UNKNOWN and normalized and normalized.split()[0] in {"3ayez", "3ayza", "3awz", "3andkom", "bekam"}:
        result.intents = [Intent.PRICE_INQUIRY if normalized.split()[0] == "bekam" else Intent.PRODUCT_INQUIRY]
    elif intent == Intent.UNKNOWN and "وريني" in normalized.split():
        from .search import search_terms
        # Explicit discovery can name any business-defined product, not only
        # nouns in the synonym dictionary. Retrieval still verifies every term;
        # known complaints and service intents retain their higher precedence.
        if search_terms(text):
            result.intents = [Intent.PRODUCT_INQUIRY]
    return result
