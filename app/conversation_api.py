"""On-demand authorized history and request-local selector reconstruction.

Uses ChatSession, never an independent conversation engine or global registry.
Only customer messages reconstruct selectors, using fresh scoped product reads.
"""
from copy import deepcopy
import hmac

from fastapi import HTTPException

from .chat.application import ChatSession
from .chat.understanding import ConversationInterpreter,needs_conversation_history
from .chat.natural import NaturalResponder
from .clients.backend_client import PRODUCT_TOOLS,CONVERSATION_TOOLS
from .data.history import HistoryService,HistoryCoverage
from .schemas.backend import Identifier, ExpectedScope, RetrievalOutcome, RetrievalStatus


class RequestProductData:
    """One HTTP request's budget/cache, shared by bounded selector replay/current turn.

    Cache entries are current Backend observations fetched within this request,
    never facts supplied by historical prose. No credentials in diagnostic repr.
    """
    def __init__(self,data,scope,token,*,allowed_tools=PRODUCT_TOOLS):
        self._data,self._scope,self._token=data,scope,token
        self._cache={}
        self.calls=0
        self._allowed_tools=allowed_tools

    def __getattr__(self,name):
        if name not in self._allowed_tools:
            async def denied(*args,**kwargs):
                return RetrievalOutcome(status=RetrievalStatus.INVALID,error="invalid_arguments")
            return denied
        async def read(*args,scope,context_token,**trusted_arguments):
            if scope != self._scope or not hmac.compare_digest(context_token,self._token):
                return RetrievalOutcome(status=RetrievalStatus.SCOPE_MISMATCH,error="scope_mismatch")
            key=(name,args,tuple(sorted(trusted_arguments.items())))
            if key in self._cache:
                return deepcopy(self._cache[key])
            if self.calls >= 12:
                return RetrievalOutcome(status=RetrievalStatus.UNAVAILABLE,error="backend_error")
            self.calls+=1
            value=await getattr(self._data,name)(*args,scope=scope,context_token=context_token,**trusted_arguments)
            if value.envelope is not None:
                self._cache[key]=deepcopy(value)
            return value
        return read


def check_authorization(execution):
    if execution.retrieval.failure in {RetrievalStatus.AUTHORIZATION_FAILED,RetrievalStatus.SCOPE_MISMATCH}:
        raise HTTPException(403,"Backend authorization rejected")


async def execute_conversation(body,token,data,interpreter,responder,settings):
    scope=ExpectedScope(business_id=body.businessId,customer_id=body.customerId,conversation_id=body.conversationId)
    bounded=RequestProductData(data,scope,token,allowed_tools=CONVERSATION_TOOLS)
    replay=ChatSession(bounded,scope,ConversationInterpreter(settings=settings),NaturalResponder(None,settings))
    status="not_requested"
    clarify=None
    if needs_conversation_history(body.message):
        prepared=await HistoryService(bounded).prepare_authorized(body.messageId,scope=scope,context_token=token)
        if prepared.failure in {RetrievalStatus.AUTHORIZATION_FAILED,RetrievalStatus.SCOPE_MISMATCH}:
            raise HTTPException(403,"Backend history authorization rejected")
        status=prepared.coverage.value
        if prepared.coverage==HistoryCoverage.COMPLETE:
            for row in prepared.messages:
                if row.sender_type!="CUSTOMER":
                    continue
                turn=await replay.send(row.content,context_token=token,message_id=row.message_id)
                check_authorization(turn.execution)
        if prepared.coverage!=HistoryCoverage.COMPLETE or len(replay.selection.products)!=1:
            clarify=interpreter.clarify_context(body.message,"history_unavailable_or_ambiguous")
    session=ChatSession(bounded,scope,interpreter,responder,initial_selection=replay.selection,repeat_current_price=True,
                        initial_order=replay.order_draft,initial_order_query=replay.order_query)
    turn=await session.send(body.message,context_token=token,message_id=body.messageId,prepared_understanding=clarify)
    check_authorization(turn.execution)
    return turn,status
