"""Non-authoritative product search projection, never an HTTP or Backend DTO.

Only name-token matching uses this shape. Prices/stock in customer responses
always originate in schemas.backend.ProductVariant, not this projection.
"""
from decimal import Decimal
from typing import Any
from uuid import UUID
from pydantic import BaseModel,ConfigDict,field_validator

class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")

class MatchingProduct(_Loose):
    """Matching-only projection. `attributes` is a flat owner-defined map, e.g. {"Material": "Cotton", "Color": "Black, Gray"}."""

    id: UUID | str
    name: str
    externalKey: str | None = None
    description: str | None = None
    category: str | None = None
    basePrice: Decimal | None = None
    trackInventory: bool = False
    stockQuantity: int | None = None
    attributes: dict[str, Any] | None = None
    isActive: bool = True

    @field_validator("attributes", mode="before")
    @classmethod
    def _attrs(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}
