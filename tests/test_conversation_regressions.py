import asyncio,json
import httpx,pytest
from tests.support import build,FakeStructured
from app.chat.application import ChatSession
from app.chat.natural import NaturalResponder
from app.chat.synthetic import SyntheticBackend,identifier
from app.chat.understanding import ConversationInterpreter,Selection
from app.schemas.response import AiResponse
@pytest.fixture
def anyio_backend():
    return "asyncio"

def session(mode="rules", business=1, customer=1):
    backend, interpreter, responder = build(mode)
    scope = backend.scope(business, customer)
    return backend, ChatSession(backend.data(), scope, interpreter, responder)

async def send(chat, backend, text):
    turn = await chat.send(text, context_token=backend.token(chat.scope))
    AiResponse.model_validate(turn.response.model_dump())
    assert turn.response.orderCandidate is None
    assert turn.response.intent.value != "CONFIRMED_ORDER"
    assert turn.execution.order_extension.enabled is False
    return turn

@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["rules", "fake"])
async def test_required_arabic_conversation(mode):
    backend, chat = session(mode)
    one = await send(chat, backend, "عندكم تيشيرت أسود؟")
    assert "الأسود" in one.response.reply and "مقاس" in one.response.reply
    two = await send(chat, backend, "طب مقاس L بكام؟")
    assert "275 جنيه" in two.response.reply and "250 جنيه" not in two.response.reply
    assert "get_variant_details" in two.tools
    assert "تحدد" not in two.response.reply
    three = await send(chat, backend, "عايزة اتنين منه.")
    assert three.response.intent.value == "PURCHASE_INTENT"
    assert three.execution.plan.requested_quantity == 2
    intent = three.execution.order_extension.purchase_intent
    assert intent.requested_quantity == 2 and intent.confirmation_required
    assert dict(intent.requested_options) == {"color": "Black", "size": "L"}
    assert all(not ref.revalidated for ref in intent.references)
    four = await send(chat, backend, "طب غيرت رأيي عايزة الأبيض.")
    assert "الأبيض" in four.response.reply and "285 جنيه" in four.response.reply
    assert "275.00" not in four.response.reply
    assert four.execution.plan.requested_quantity == 2
    if mode == "fake":
        assert four.understanding.source == "groq_understanding"
        assert four.execution.generation.source == "groq_conversation"

@pytest.mark.anyio
@pytest.mark.parametrize("messages", [
    ["Do you have a black tshirt?", "How much is size L?", "I want two of it"],
    ["3andkom tshirt eswed", "bekam size L", "3ayez etneen meno"],
])
async def test_english_and_franco_followups(messages):
    backend, chat = session("fake")
    turns = [await send(chat, backend, message) for message in messages]
    assert any(price in turns[1].response.reply for price in ("275.00 EGP","275 جنيه","275 geneh"))
    assert turns[2].execution.plan.requested_quantity == 2
    assert turns[2].response.intent.value == "PURCHASE_INTENT"

@pytest.mark.anyio
async def test_fresh_inventory_not_previous_reply_authority():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    v = backend.products[1][0]["variants"][1]
    v.update(unitPrice="299.95", effectivePrice="299.95", stockQuantity=0)
    turn = await send(chat, backend, "How much is it?")
    assert "299.95" in turn.response.reply and "275.00" not in turn.response.reply
    assert "out of stock" in turn.response.reply and "recorded stock" not in turn.response.reply
    assert next(v for v in turn.execution.plan.variants if v.variant_id in turn.execution.plan.matching_variant_ids).recorded_quantity == 0

@pytest.mark.anyio
async def test_arbitrary_arabic_options_followup():
    backend, chat = session()
    product = backend.products[1][0]
    product["options"] = {"التشطيب": ["مطفي", "لامع"]}
    product["variants"] = product["variants"][:2]
    for v, finish in zip(product["variants"], ["مطفي", "لامع"]):
        v["optionValues"] = {"التشطيب": finish}
    product["variantsPagination"]["totalCount"] = 2
    await send(chat, backend, "tshirt price")
    turn = await send(chat, backend, "التشطيب: مطفي")
    assert "250 جنيه" in turn.response.reply
    assert "275.00" not in turn.response.reply
    assert "مطفي" in turn.response.reply

@pytest.mark.anyio
async def test_scope_mismatch_discards_all_evidence():
    backend, chat = session()
    backend.products[1][0]["businessId"] = identifier(1, 2)
    turn = await send(chat, backend, "black tshirt price")
    assert turn.execution.retrieval.failure.value == "scope_mismatch"
    assert not turn.execution.plan.products and not chat.selection.products
    assert "250.00" not in turn.response.reply

@pytest.mark.anyio
async def test_backend_timeout_has_no_stale_reply():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    def timeout(request):
        raise httpx.ReadTimeout("synthetic-service should never escape")
    chat._data._client._transport = httpx.MockTransport(timeout)
    turn = await send(chat, backend, "How much is it?")
    assert "275.00" not in turn.response.reply and "synthetic-service" not in turn.response.reply
    assert not chat.selection.products

@pytest.mark.anyio
async def test_similar_products_are_not_silently_selected():
    from copy import deepcopy
    backend, chat = session()
    duplicate = deepcopy(backend.products[1][0])
    duplicate.update(id=identifier(4, 999), name="تيشيرت قطن Cotton T-Shirt Premium")
    for i, variant in enumerate(duplicate["variants"]):
        variant.update(catalogItemId=duplicate["id"], id=identifier(5, 900 + i))
    backend.products[1].append(duplicate)
    turn = await send(chat, backend, "black tshirt price")
    assert len(turn.execution.plan.products) == 2
    assert "Which product" in turn.response.reply
    assert "275.00" not in turn.response.reply
    next_turn = await send(chat, backend, "size L")
    assert not next_turn.understanding.inquiry.product_ids

@pytest.mark.anyio
async def test_quantity_shortfall_is_provisional_and_explained():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    turn = await send(chat, backend, "I want 9 of it")
    assert turn.execution.plan.requested_quantity == 9
    assert "full requested quantity is not currently available" in turn.response.reply
    assert "review availability" in turn.response.reply and turn.response.requiresReview
    assert "4" not in turn.response.reply and turn.response.orderCandidate is None
    assert next(v for v in turn.execution.plan.variants if v.variant_id in turn.execution.plan.matching_variant_ids).recorded_quantity == 4

@pytest.mark.anyio
@pytest.mark.parametrize("text,includes,excludes", [
    ("white tshirt size M price", "225.00 EGP", "stock: 0"),
    ("blue tshirt size M price", "0.00 EGP", "200.00"),
    ("blue tshirt size L price", "can't verify an active variant", "205.00"),
    ("cap price", "price unconfirmed", "0.00 EGP"),
    ("tshirt price", "Which color / size", "Which product"),
])
async def test_inventory_and_clarification(text, includes, excludes):
    backend, chat = session()
    turn = await send(chat, backend, text)
    assert includes in turn.response.reply
    assert excludes not in turn.response.reply

@pytest.mark.anyio
@pytest.mark.parametrize("text", ["delivery tomorrow?", "What is your return policy?", "I want a refund", "My order never arrived"])
async def test_unsupported_or_review_cannot_become_product_or_order(text):
    backend, chat = session("fake")
    turn = await send(chat, backend, text)
    assert not turn.execution.plan.variants
    assert not backend.calls
    assert "275.00" not in turn.response.reply

@pytest.mark.anyio
async def test_complaint_escalation():
    backend, chat = session("fake")
    turn = await send(chat, backend, "I have a complaint, my order is late")
    assert turn.response.requiresReview
    assert turn.understanding.source == "rules"

@pytest.mark.anyio
async def test_context_reset_and_new_product_supersedes():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    cap = await send(chat, backend, "cap price")
    assert "275.00" not in cap.response.reply
    await chat.reset()
    turn = await send(chat, backend, "size L price")
    assert turn.understanding.inquiry.product_ids == ()

@pytest.mark.anyio
async def test_unrecognized_new_noun_does_not_inherit_product():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    turn = await send(chat, backend, "What about a red mug?")
    assert not turn.understanding.inquiry.product_ids
    assert "275.00" not in turn.response.reply

@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_failure_clears_context_and_no_cached_prices(status):
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    backend.status_code = status
    turn = await send(chat, backend, "size L price")
    assert not chat.selection.products
    assert "275.00" not in turn.response.reply
    assert "synthetic-service" not in turn.response.reply

@pytest.mark.anyio
async def test_concurrent_customers_and_businesses_have_separate_context():
    backend, interpreter, responder = build("fake")
    chats = [ChatSession(backend.data(), backend.scope(b, c), interpreter, responder)
             for b, c in [(1, 1), (1, 2), (2, 1), (2, 2)]]
    await asyncio.gather(*(send(c, backend, text) for c, text in zip(chats,
        ["black tshirt size L price", "white tshirt size M price", "blue tshirt size M price", "cap price"])))
    turns = await asyncio.gather(*(send(c, backend, "How much is it?") for c in chats))
    assert "275.00" in turns[0].response.reply
    assert "225.00" in turns[1].response.reply
    assert "0.00 EGP" in turns[2].response.reply
    assert "price unconfirmed" in turns[3].response.reply
    assert not hasattr(interpreter, "selection") and not hasattr(responder, "last_plan")

@pytest.mark.anyio
@pytest.mark.parametrize("proposal", [
    '{"tone":"friendly","acts":[],"reply":"The price is 1 and your order is confirmed"}',
    '{"tone":"friendly","acts":[]}',
    '{"tone":"friendly","acts":[{"fact_id":"f0","phrase":2}]}',
    'The price is 1.00 EGP and stock is unlimited.',
    '{"tone":"direct","acts":[{"fact_id":"foreign","phrase":0}]}',
])
async def test_adversarial_generation_cannot_change_facts(proposal):
    backend, chat = session()
    turn = await send(chat, backend, "black tshirt size L price")
    fake = FakeStructured({"g-a": proposal, "g-b": proposal}, gemini_max_retries=0)
    generation = await NaturalResponder(fake, fake.settings).generate(turn.execution.plan)
    assert generation.fallback_reason == "reply_unavailable_or_guard_rejected"
    assert "275.00 EGP" in generation.response.reply
    assert "unlimited" not in generation.response.reply
    assert generation.response.orderCandidate is None

@pytest.mark.anyio
@pytest.mark.parametrize("patch", [
    {"businessId": "attacker"}, {"product_handle": "p99"}, {"quantity": True},
    {"options": {"color": "x" * 101}}, {"act": "execute_http"},
])
async def test_adversarial_understanding_falls_back(patch):
    payload = dict(act="price", product_handle=None, search="tshirt", options={}, quantity=None, language="en")
    payload.update(patch)
    fake = FakeStructured({"r-a": json.dumps(payload), "r-b": json.dumps(payload)}, gemini_max_retries=0)
    result = await ConversationInterpreter(fake, fake.settings).understand("black tshirt price", Selection())
    assert result.source == "rules" and result.fallback
    assert not result.inquiry.product_ids

@pytest.mark.anyio
async def test_structured_model_understands_semantics_beyond_rules_hint():
    # Model-selected interpretation performs useful work, not presentation only.
    payload = dict(act="price", product_handle=None, search="tshirt", options={"color": "White", "size": "M"},
                   quantity=None, language="en")
    fake = FakeStructured({"r-a": json.dumps(payload)})
    backend = SyntheticBackend()
    chat = ChatSession(backend.data(), backend.scope(), ConversationInterpreter(fake, fake.settings), NaturalResponder())
    turn = await send(chat, backend, "Could you tell me what the pale medium tee goes for?")
    assert turn.understanding.source == "groq_understanding"
    assert "225.00 EGP" in turn.response.reply
    assert "available" not in turn.response.reply.lower()

@pytest.mark.anyio
async def test_model_can_raise_review_for_a_novel_complaint():
    payload = dict(act="review", product_handle=None, search="", options={}, quantity=None, language="en")
    fake = FakeStructured({"r-a": json.dumps(payload)})
    backend = SyntheticBackend()
    chat = ChatSession(backend.data(), backend.scope(), ConversationInterpreter(fake, fake.settings), NaturalResponder())
    turn = await send(chat, backend, "The stitching came apart as soon as I put it on")
    assert turn.response.requiresReview
    assert turn.understanding.source == "groq_understanding"
    assert not backend.calls

@pytest.mark.anyio
@pytest.mark.parametrize("text", ["hello", "شكرا", "yes", "لا", "How do I use this bot?"])
async def test_simple_messages_do_not_call_gemini(text):
    class NoProvider:
        async def call(self, **kwargs):
            raise AssertionError("hard rules should not invoke a provider")
    backend = SyntheticBackend()
    interpreter = ConversationInterpreter(NoProvider())
    # AssertionError is intentionally checked through source/fallback because
    # untrusted provider exceptions must be sanitized by application code.
    turn = await ChatSession(backend.data(), backend.scope(), interpreter, NaturalResponder()).send(
        text, context_token=backend.token(backend.scope()))
    assert turn.understanding.source == "rules"
    assert turn.understanding.fallback is None
    assert not backend.calls

@pytest.mark.anyio
async def test_decline_clears_provisional_selection():
    backend, chat = session("fake")
    await send(chat, backend, "I want two black tshirt size L")
    await send(chat, backend, "no")
    assert not chat.selection.products and chat.selection.quantity is None

@pytest.mark.anyio
async def test_prior_observations_and_authentication_are_not_provider_inputs():
    backend, chat = session()
    await send(chat, backend, "black tshirt size L price")
    payload = dict(act="price", product_handle="p0", search="", options={}, quantity=None, language="en")
    fake = FakeStructured({"r-a": json.dumps(payload)})
    chat.interpreter = ConversationInterpreter(fake, fake.settings)
    turn = await send(chat, backend, "How much is it?")
    prompt = fake.calls[0][2]
    assert "275.00" not in prompt and "stockQuantity" not in prompt
    assert str(chat.scope.business_id) not in prompt and str(chat.scope.customer_id) not in prompt
    assert backend.token(chat.scope) not in prompt
    assert "275.00 EGP" in turn.response.reply

from app.chat.understanding import Meaning
from app.providers.structured import parse_structured, StructuredOutputError
from pydantic import ValidationError


MEANING = dict(act="price", product_handle=None, search="tshirt", options={"size": "L"}, quantity=None, language="en")
from app.chat.natural import NaturalReply as ConversationReply
REPLY={"sentences":[{"fact_ids":["f0"],"join":"and"}],"warmth":"neutral","question_style":"direct"}
@pytest.mark.parametrize("schema,payload", [(Meaning, MEANING), (ConversationReply, REPLY)])
@pytest.mark.parametrize("kind", ["missing", "malformed", "null", "wrong", "extra", "empty", "oversized"])
def test_strict_structured_parsing(schema, payload, kind):
    text = json.dumps(payload)
    expected = "validation_error"
    if kind == "missing":
        text, expected = "{}", "missing_fields"
    elif kind == "malformed":
        text, expected = "{broken", "malformed_json"
    elif kind == "null":
        text = "null"
    elif kind == "wrong":
        text = '[]'
    elif kind == "extra":
        text = json.dumps({**payload, "reply": "secret customer content"})
    elif kind == "empty":
        text, expected = None, "empty_output"
    elif kind == "oversized":
        text, expected = "x" * 4097, "output_limit"
    with pytest.raises(StructuredOutputError) as error:
        parse_structured(schema, text)
    assert error.value.category == expected
    assert "secret" not in str(error.value)

@pytest.mark.anyio
async def test_reported_arabic_preference_regression():
    for mode in ("rules", "fake"):
        backend, interpreter, responder = build(mode)
        scope = backend.scope()
        chat = ChatSession(backend.data(), scope, interpreter, responder)
        for message in ("عندكم تيشيرت أسود؟", "طب مقاس L بكام؟", "عايزة اتنين منه",
                        "طب غيرت رأيي عايزة الأبيض"):
            await chat.send(message, context_token=backend.token(scope))
        last = await chat.send("أنا محتارة بين الأسود والأبيض، وعايزة مقاس L بس مش عارفة أنهي لون أحسن",
                               context_token=backend.token(scope))
        assert last.understanding.meaning.act == "compare"
        assert last.understanding.inquiry.product_ids
        assert last.response.intent.value == "INQUIRY"
        assert last.execution.plan.requested_quantity is None
        assert len(last.execution.plan.matching_variant_ids) == 2
        assert "275 جنيه" in last.response.reply and "285 جنيه" in last.response.reply
        assert "لون" in last.response.reply and "أفضل" not in last.response.reply
        assert "أنهي منتج" not in last.response.reply
        assert last.response.orderCandidate is None

@pytest.mark.anyio
@pytest.mark.parametrize("text", ["never mind", "مش عايزة خلاص", "cancel"])
async def test_cancellation_never_executes_order_and_clears_provisional_purchase(text):
    backend, interpreter, responder = build("fake")
    scope = backend.scope()
    chat = ChatSession(backend.data(), scope, interpreter, responder)
    await chat.send("I want two black tshirt size L", context_token=backend.token(scope))
    cancelled = await chat.send(text, context_token=backend.token(scope))
    assert cancelled.response.orderCandidate is None
    assert cancelled.response.intent.value == "OTHER"
    assert "leave that option" in cancelled.response.reply or "نسيب الاختيار" in cancelled.response.reply
    assert "cancelled your order" not in cancelled.response.reply
    assert not chat.selection.products
    assert chat.selection.quantity is None
    fresh = await chat.send("I want three white tshirt size M", context_token=backend.token(scope))
    assert fresh.response.intent.value == "PURCHASE_INTENT"
    assert fresh.execution.plan.requested_quantity == 3
    assert "225.00 EGP" in fresh.response.reply

@pytest.mark.anyio
async def test_new_unrelated_product_does_not_inherit_purchase_or_quantity():
    backend, interpreter, responder = build("rules")
    scope = backend.scope()
    chat = ChatSession(backend.data(), scope, interpreter, responder)
    await chat.send("I want two black tshirt size L", context_token=backend.token(scope))
    turn = await chat.send("What about a red mug?", context_token=backend.token(scope))
    assert turn.response.intent.value != "PURCHASE_INTENT"
    assert not turn.understanding.inquiry.product_ids
    assert turn.execution.plan.requested_quantity is None
    assert not chat.selection.products and chat.selection.quantity is None

@pytest.mark.anyio
@pytest.mark.parametrize("patch", [{"stockQuantity": 0}, {"isActive": False}, {"unitPrice": None,"effectivePrice": None}])
async def test_comparison_revalidates_changed_evidence(patch):
    backend, interpreter, responder = build("rules")
    scope = backend.scope()
    chat = ChatSession(backend.data(), scope, interpreter, responder)
    await chat.send("black tshirt size L price", context_token=backend.token(scope))
    backend.products[1][0]["variants"][2].update(patch)
    turn = await chat.send("Compare black and white size L", context_token=backend.token(scope))
    assert turn.response.intent.value == "INQUIRY"
    assert "275.00 EGP" in turn.response.reply
    if patch.get("isActive") is False:
        assert "285.00 EGP" not in turn.response.reply
        assert "Not all requested alternatives" in turn.response.reply
    elif "unitPrice" in patch:
        assert "285.00 EGP" not in turn.response.reply
        assert "price unconfirmed" in turn.response.reply
    else:
        assert "out of stock" in turn.response.reply and "recorded stock" not in turn.response.reply

def test_duplicate_json_fields_are_rejected():
    with pytest.raises(StructuredOutputError, match="duplicate_fields"):
        parse_structured(ConversationReply, '{"tone":"direct","tone":"friendly","acts":[]}')

@pytest.mark.anyio
async def test_changing_mind_changes_selection_without_inheriting_purchase_intent():
    backend, interpreter, responder = build("fake")
    scope = backend.scope()
    chat = ChatSession(backend.data(),scope,interpreter,responder)
    await chat.send("I want two black tshirt size L",context_token=backend.token(scope))
    turn = await chat.send("Actually I changed my mind, make it white",context_token=backend.token(scope))
    assert turn.understanding.inquiry.product_ids
    assert "285.00 EGP" in turn.response.reply and "275.00 EGP" not in turn.response.reply
    assert turn.response.intent.value == "INQUIRY"
    assert turn.execution.plan.requested_quantity is None
