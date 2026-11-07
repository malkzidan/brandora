"""Cross-version policies exercised exclusively through the canonical engine."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, ConfigError, load_settings, parse_port
from app.offline_demo import OfflineHarness
from app.pipeline.evidence_guard import validate_final_response
from app.chat.natural import NaturalResponder
from app.providers.evidence import GroundedGeneration
from app.schemas.backend import Product, ProductVariant


@pytest.mark.parametrize("message,review", [
    ("أهلا",False),("شكرا",False),("how do I order?",False),
    ("أنا دفعت ومحدش رد",True),("هشتكي عليكم",True),
    ("I paid and nobody replied",True),("I will sue you",True),
    ("عندي شكوى",True),("I want a custom design",True),
    ("where is my order",False),("I want to cancel my order",False),
    ("ممكن أعدل الطلب؟",False),("إزاي أرجع المنتج؟",False),
    ("Do you accept card payments?",False),("What are your working hours?",False),
])
def test_v1_service_intents_remain_safe_without_supplied_facts(message,review):
    h=OfflineHarness()
    result=h.send(h.body(message))
    assert result.status_code==200,result.text
    body=result.json()
    assert body["requiresReview"] is review
    assert body["orderCandidate"] is None
    assert all(c["tool"] in {"get_conversation_history","get_products","get_product_details",
                            "get_product_variants","get_variant_details"} for c in h.calls)
    for claim in ("order confirmed","order has been cancelled","owner has been notified",
                  "تم إبلاغ","تم إخطار","تم تأكيد طلبك","تم إلغاء طلبك"):
        assert claim not in body["reply"]


def contract_product():
    return json.loads((Path(__file__).parent/"fixtures/product-management.json").read_text(encoding="utf-8"))["product"]


def test_actual_presenter_fields_are_preserved_and_images_are_not_variant_evidence():
    raw=contract_product()
    product=Product.model_validate(raw)
    assert product.images[0].productId==product.id
    assert product.images[0].secureUrl==raw["images"][0]["secureUrl"]
    assert product.colorOptionName=="color"
    assert product.variants[0].productId==product.id
    assert product.variants[0].sku==raw["variants"][0]["sku"]


@pytest.mark.parametrize("alias",["productId","catalogItemId"])
def test_each_parent_alias_is_supported_without_recomputing_price(alias):
    raw=contract_product()["variants"][0]
    raw.pop("catalogItemId" if alias=="productId" else "productId")
    raw.update(unitPrice="0.00",effectivePrice="0.00")
    variant=ProductVariant.model_validate(raw)
    assert variant.effectivePrice==0 and variant.productId==variant.catalogItemId


def test_conflicting_parent_aliases_fail_closed():
    raw=contract_product()["variants"][0]
    raw["productId"]="00000000-0000-4000-8000-000000000099"
    with pytest.raises(ValidationError):
        ProductVariant.model_validate(raw)


@pytest.mark.parametrize("patch",[{"isMain":False},{"position":5},{"secureUrl":"http://untrusted.invalid/image"},
    {"productId":"00000000-0000-4000-8000-000000000099"},{"bytes":-1}])
def test_malformed_image_metadata_is_rejected(patch):
    raw=contract_product()
    raw["images"][0].update(patch)
    with pytest.raises(ValidationError):
        Product.model_validate(raw)


@pytest.mark.parametrize("name,value",[
    ("AI_INTEGRATION_ENABLED","yes"),("GENERATOR_ENABLED","maybe"),("GENERATOR_ENABLED",""),
    ("BACKEND_TIMEOUT_SECONDS","nan"),("BACKEND_TIMEOUT_SECONDS","inf"),
    ("BACKEND_TIMEOUT_SECONDS","bad"),("BACKEND_TIMEOUT_SECONDS",""),
    ("CHAT_TOTAL_TIMEOUT_SECONDS","0"),("INTEGRATION_TIMEOUT_SECONDS","26"),
    ("GROQ_MODELS",""),("GROQ_MODELS","model,,other"),("APP_ENV","invalid"),
    ("AI_PROVIDER","gemini"),("AI_PROVIDER","openrouter"),
    ("BACKEND_BASE_URL","https://user:password@example.invalid"),
    ("BACKEND_BASE_URL","http://remote.invalid"),("TRUSTED_PROXY_CIDRS","0.0.0.0/0"),
    ("LEGACY_API_ENABLED","true"),("PRODUCTS_INTEGRATION_ENABLED","true"),
    ("SUPPLIED_CONTEXT_COMPAT_ENABLED","true"),("ENABLE_DEV_ENDPOINTS","true"),
])
def test_strict_environment_parsing(monkeypatch,name,value):
    monkeypatch.setenv(name,value)
    with pytest.raises(ConfigError):
        load_settings()


@pytest.mark.parametrize("value",["0","65536","1.5","nan","-1"," 80","", "٨٠"])
def test_invalid_port_cannot_start(value):
    with pytest.raises(ConfigError):
        parse_port(value)


@pytest.mark.parametrize("env",["staging","production"])
def test_release_cannot_use_unconfigured_python_only_mode(env):
    with pytest.raises(ConfigError):
        Settings(app_env=env).validate()


@pytest.mark.parametrize("claim",["The price is 1 EGP", "Order confirmed", "I will notify the owner",
    "We reserved 100 units", "Stock is guaranteed", "Restock tomorrow", "تم تأكيد طلبك", "تم إبلاغ صاحب المحل"])
def test_final_guard_rejects_arbitrary_composer_even_when_fields_are_valid(claim):
    from tests.support import build
    from app.chat.application import ChatSession
    async def run():
        b,i,r=build()
        turn=await ChatSession(b.data(),b.scope(),i,r).send("black tshirt size L price",context_token=b.token(b.scope()))
        forged=turn.response.model_copy(update={"reply":claim})
        assert not validate_final_response(turn.execution.plan,forged)
        assert validate_final_response(turn.execution.plan,turn.response)
    asyncio.run(run())


def test_pipeline_applies_guard_after_injected_generation():
    from tests.test_standalone_pipeline import setup,execute
    class BrokenComposer(NaturalResponder):
        async def generate(self,plan):
            return GroundedGeneration(plan.to_response().model_copy(update={"reply":"Order confirmed at 1 EGP"}),"forged")
    pipeline,_,_=setup()
    pipeline._generator=BrokenComposer()
    result=execute(pipeline)
    assert result.generation.fallback_reason=="final_evidence_guard_rejected"
    assert "1 EGP" not in result.response.reply
    assert validate_final_response(result.plan,result.response)


def test_only_one_conversation_route_and_no_production_test_imports():
    import sys
    h=OfflineHarness()
    paths={path for path, operations in h.app.openapi()["paths"].items() if "post" in operations}
    assert paths=={"/v2/ai/respond"}
    import subprocess
    result=subprocess.run([sys.executable,"-c","from app.http import create_app; create_app(); import sys; assert not any(n.startswith(('tests','app.offline_demo','app.chat.synthetic')) for n in sys.modules)"],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_backend_response_payload_limit():
    from app.clients.backend_client import BackendClient,BackendResponseError
    client=BackendClient("https://backend.invalid","test-token",transport=httpx.MockTransport(
        lambda request:httpx.Response(200,content=b"x"*131073)))
    with pytest.raises(BackendResponseError,match="payload limit"):
        asyncio.run(client.get_products(context_token="synthetic"))


def test_duplicate_authentication_header_is_rejected_before_inference():
    h=OfflineHarness()
    raw,headers=h.encode(h.body("hi"))
    response=TestClient(h.app).post("/v2/ai/respond",content=raw,
        headers=[*headers.items(),("X-Internal-Token","duplicate")])
    assert response.status_code==400 and not h.model_calls and not h.calls


def test_multivariant_availability_has_one_final_stock_caveat():
    h=OfflineHarness()
    result=h.send(h.body("عندكم تيشيرت أسود؟"))
    assert result.status_code==200
    assert result.json()["reply"].count("التوافر النهائي محتاج تأكيد")==1
    assert "M" in result.json()["reply"] and "L" in result.json()["reply"]
