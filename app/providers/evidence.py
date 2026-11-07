from dataclasses import dataclass, field
from typing import Protocol
from ..schemas.response import AiResponse
from ..pipeline.evidence_planner import EvidencePlan
from .structured import ProviderDiagnostic

@dataclass(frozen=True)
class GroundedGeneration:
    response: AiResponse = field(repr=False)
    source: str
    model: str | None = None
    fallback_reason: str | None = None
    guard_violations: tuple[str, ...] = ()
    provider_diagnostics: tuple[ProviderDiagnostic, ...] = ()


class EvidenceResponder(Protocol):
    """Stable plan/response boundary for future multilingual conversation.

    Implementations must retain evidence validation, required clarification/review,
    read-only output and deterministic fallback. This interface enables no new
    generation mode by itself. NaturalResponder supplies the shared composer;
    the execution pipeline independently applies the final evidence guard.
    """
    async def generate(self, plan: EvidencePlan) -> GroundedGeneration: ...

    def fallback(self, plan: EvidencePlan, reason: str, violations=()) -> GroundedGeneration: ...
