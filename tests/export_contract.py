"""Regenerate review schemas from the authoritative Python models."""
import json
from pathlib import Path
from app.api import ConversationRequest,ConversationClaims,CanonicalResponse
from app.schemas.backend import Product,ProductVariant,AuthorizedHistoryPage

def main():
    models=(ConversationRequest,ConversationClaims,CanonicalResponse,Product,ProductVariant,AuthorizedHistoryPage)
    target=Path(__file__).resolve().parents[1]/"docs/verification/contract-schemas.json"
    target.write_text(json.dumps({m.__name__:m.model_json_schema() for m in models},ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
