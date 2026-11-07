"""Canonical authenticated conversation HTTP boundary.

RS256 context claims match Backend feature/backend-ai-integration. Main and live
deployment availability are separate. No token signing or key discovery here.
"""
import hmac
import time
import asyncio
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from google.auth import jwt
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from .clients.backend_client import BackendClient, CONVERSATION_TOOLS
from .data.backend import BackendDataAccess
from .chat.understanding import ConversationInterpreter
from .chat.natural import NaturalResponder
from .providers.groq import GroqClient
from .schemas.backend import Identifier
from .schemas.response import AiResponse, E03Intent
from .conversation_api import execute_conversation


class ConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    businessId: Identifier
    customerId: Identifier
    conversationId: Identifier
    messageId: Identifier
    message: StrictStr = Field(min_length=1,max_length=2000,repr=False)

    @field_validator("message")
    @classmethod
    def nonblank(cls,value):
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value.strip()


class ConversationClaims(BaseModel):
    model_config = ConfigDict(extra="forbid",frozen=True)
    iss: Literal["brandora-backend"]
    aud: Literal["brandora-ai-tools-v1"]
    scope: Literal["products:read conversations:read"]
    businessId: Identifier
    customerId: Identifier
    conversationId: Identifier
    messageId: Identifier
    requestHash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    iat: StrictInt
    exp: StrictInt


class CanonicalResponse(AiResponse):
    intent: Literal[E03Intent.INQUIRY, E03Intent.PURCHASE_INTENT, E03Intent.OTHER]
    orderCandidate: None


def validate_canonical_result(result):
    """Bound canonical output; preserve general E0-3 schemas."""
    if (result.orderCandidate is not None or result.intent.value == "CONFIRMED_ORDER"
            or not result.reply.strip() or len(result.reply) > 20000
            or len(result.model_dump_json().encode("utf-8")) > 65536):
        raise ValueError("Invalid canonical response")
    return CanonicalResponse.model_validate(result.model_dump(mode="json"))

def build_conversation_router(settings, *, transport=None, model_client=None):
    """Only called when explicitly enabled; injected transports are test seams."""
    settings.validate()
    inbound=settings.ai_service_token
    outbound=settings.backend_service_token
    public_key=settings.backend_context_public_key
    if model_client is None:
        model_client = GroqClient(settings) if settings.ai_provider == "groq" else None
    interpreter = ConversationInterpreter(model_client,settings)
    responder = NaturalResponder(model_client,settings)
    router = APIRouter()

    def authenticate(request,x_internal_token,x_ai_context,*,claim_type=ConversationClaims,audience="brandora-ai-tools-v1"):
        if settings.app_env not in {"local","test"} and request.url.scheme != "https":
            raise HTTPException(400,"HTTPS required")
        if (not x_internal_token or len(x_internal_token) > 4096
                or not hmac.compare_digest(x_internal_token.encode("utf-8"),inbound.encode("utf-8"))):
            raise HTTPException(401,"Invalid service authentication")
        try:
            if not x_ai_context or len(x_ai_context) > 8192:
                raise ValueError()
            header = jwt.decode_header(x_ai_context)
            if (header.get("alg") != "RS256" or header.get("typ") != "JWT"
                    or set(header) != {"alg","typ"}):
                raise ValueError()
            claims = claim_type.model_validate(jwt.decode(x_ai_context,certs=public_key,
                audience=audience,verify=True,clock_skew_in_seconds=0))
            now = time.time()
            if not (0 <= claims.iat <= now < claims.exp <= claims.iat + 60):
                raise ValueError()
        except Exception:
            raise HTTPException(401,"Invalid Backend context") from None
        # Token remains a per-call header, never a shared field or model input.
        return claims,x_ai_context

    canonical_data=BackendDataAccess(BackendClient(settings.backend_base_url,outbound,timeout=settings.backend_timeout_seconds,
                               allowed_tools=CONVERSATION_TOOLS,transport=transport))
    async def authenticate_conversation(request: Request,x_internal_token: str | None = Header(default=None),
                     x_ai_context: str | None = Header(default=None)):
        claims,token=authenticate(request,x_internal_token,x_ai_context,
                                  claim_type=ConversationClaims,audience="brandora-ai-tools-v1")
        if not hmac.compare_digest(claims.requestHash,hashlib.sha256(await request.body()).hexdigest()):
            raise HTTPException(403,"Backend context body binding mismatch")
        return claims,token

    @router.post("/v2/ai/respond",response_model=CanonicalResponse,tags=["ai-integration"])
    async def conversation(body: ConversationRequest,response: Response,verified=Depends(authenticate_conversation)):
        claims,token=verified
        if any(getattr(claims,key) != getattr(body,key) for key in
               ("businessId","customerId","conversationId","messageId")):
            raise HTTPException(403,"Backend context binding mismatch")
        try:
            turn,history_status=await asyncio.wait_for(execute_conversation(body,token,canonical_data,interpreter,responder,settings),
                                        timeout=settings.integration_timeout_seconds)
            result=validate_canonical_result(turn.response)
            response.headers["X-AI-History-Status"]=history_status
            response.headers["X-AI-Contract"]="conversation-tools-v1"
            response.headers["X-AI-Understanding-Provider"]=turn.understanding.source.split("_")[0]
            response.headers["X-AI-Reply-Provider"]=turn.diagnostics()["replyProvider"]
            response.headers["X-AI-Message-Id"]=str(body.messageId)
            return result
        except HTTPException:
            raise
        except asyncio.TimeoutError:
            raise HTTPException(503,"AI request deadline exceeded") from None
        except Exception:
            raise HTTPException(503,"AI response unavailable") from None


    return router
