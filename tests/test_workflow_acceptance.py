"""Signed canonical Product-tool workflow with observable, synthetic evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.chat.synthetic import identifier
from tests.workflow_probe import TracedHarness,product_fixture


JOURNEY=("عندكم تيشيرت أسود؟","طب مقاس L بكام؟","طب عايزة 10 قطع من مقاس L",
         "طب خلاص خليهم 3 قطع من الأبيض مقاس L بدل الأسود")


def harness(failure=None):
    value=TracedHarness()
    value.backend.products[1]=product_fixture()
    value.model_failure=failure
    return value


def checked(h,message,label="fixture"):
    response,trace=h.traced_send(message,label=label)
    assert response.status_code==200,response.text
    assert trace["execution"]["finalGuardPassed"]
    assert response.json()["orderCandidate"] is None
    assert not trace["execution"]["ordersEnabled"]
    return trace


@pytest.mark.parametrize("failure",[None,503,"json"])
def test_required_workflow_uses_current_backend_shaped_evidence(failure):
    h=harness(failure)
    traces=[checked(h,text,f"journey-{i}") for i,text in enumerate(JOURNEY,1)]
    assert traces[0]["execution"]["historyStatus"]=="not_requested"
    assert all(t["execution"]["historyStatus"]=="complete" for t in traces[1:])
    assert "get_products" in [t["tool"] for t in traces[0]["toolCallbacks"]]
    assert all(any(t["tool"]=="get_variant_details" for t in turn["toolCallbacks"]) for turn in traces[1:])
    assert traces[2]["execution"]["quantity"]==10
    assert traces[2]["execution"]["response"]["requiresReview"]
    last=traces[3]["execution"]
    assert last["quantity"]==3 and last["response"]["intent"]=="PURCHASE_INTENT"
    assert len(last["facts"])==1
    assert last["facts"][0]["options"]=={"Color":"White","Size":"L"}
    assert last["facts"][0]["effectivePrice"]=="290.00"
    assert last["facts"][0]["recordedQuantity"]==3
    assert not last["response"]["requiresReview"]
    assert "275" not in last["response"]["reply"]
    assert all(call["schemaValid"] for turn in traces for call in turn["toolCallbacks"])
    serialized=json.dumps(traces,ensure_ascii=False)
    for secret in (h.settings.ai_service_token,h.settings.backend_service_token,"X-AI-Context","Bearer "):
        assert secret not in serialized


@pytest.mark.parametrize("text,price",[("عندكم تيشيرتات؟",None),
    ("بكام التيشيرت الأسود مقاس L؟","275.00"),("طب وريني القميص الكتان","350.00")])
def test_independent_questions_call_product_tools_without_history(text,price):
    h=harness()
    trace=checked(h,text)
    assert trace["execution"]["historyStatus"]=="not_requested"
    assert "get_products" in [c["tool"] for c in trace["toolCallbacks"]]
    if price:
        assert trace["execution"]["facts"][0]["effectivePrice"]==price


def test_followup_stock_disclosure_and_comparison_stay_grounded():
    h=harness()
    checked(h,JOURNEY[0]);checked(h,JOURNEY[1])
    stock=checked(h,"متوفر منه كام قطعة؟")
    assert stock["execution"]["historyStatus"]=="complete"
    assert stock["execution"]["facts"][0]["recordedQuantity"]==7
    assert "7" not in stock["execution"]["response"]["reply"] # default disclosure denied
    comparison=checked(h,"أنهي أرخص، الأسود L ولا الأبيض L؟")
    assert {f["effectivePrice"] for f in comparison["execution"]["facts"]}=={"275.00","290.00"}
    assert comparison["execution"]["response"]["intent"]=="INQUIRY"
    assert "15" in comparison["execution"]["response"]["reply"]


def test_missing_combination_never_substitutes_black_inventory():
    h=harness();checked(h,JOURNEY[0])
    trace=checked(h,"عندكم الأبيض مقاس M؟")
    assert trace["execution"]["facts"]==[]
    assert "250" not in trace["execution"]["response"]["reply"]
    assert trace["execution"]["selectedVariantId"] is None


def test_last_variant_is_found_beyond_twenty_embedded_records():
    h=harness()
    product=h.backend.products[1][0]
    variant=deepcopy(product["variants"][0])
    product["options"]={"Color":["Black"],"Size":[f"S{i}" for i in range(22)]+["L"]}
    product["variants"]=[]
    for index,size in enumerate(product["options"]["Size"]):
        row=deepcopy(variant)
        row.update(id=identifier(5,500+index),optionValues={"Color":"Black","Size":size})
        product["variants"].append(row)
    trace=checked(h,"بكام التيشيرت الأسود مقاس L؟")
    assert any(c["tool"]=="get_product_variants" and c["arguments"]["offset"]==20 for c in trace["toolCallbacks"])
    assert trace["execution"]["matchingVariantIds"]==[product["variants"][-1]["id"]]


def test_multiple_products_are_not_silently_reduced_to_first_match():
    h=harness()
    other=deepcopy(h.backend.products[1][0]);other["id"]=identifier(4,999)
    for i,row in enumerate(other["variants"]):
        row.update(id=identifier(5,900+i),productId=other["id"],catalogItemId=other["id"])
    for image in other["images"]:image["productId"]=other["id"]
    h.backend.products[1].append(other)
    trace=checked(h,"بكام التيشيرت الأسود مقاس L؟")
    assert len(trace["execution"]["productIds"])==2
    assert trace["execution"]["selectedVariantId"] is None


def export(path):
    h=harness()
    for i,text in enumerate(JOURNEY,1):checked(h,text,f"required-turn-{i}")
    checked(h,"متوفر منه كام قطعة؟","stock-followup")
    checked(h,"أنهي أرخص، الأسود L ولا الأبيض L؟","price-comparison")
    checked(h,"عندكم الأبيض مقاس M؟","missing-combination")
    checked(h,"طب وريني القميص الكتان","switch-product")
    for label,text in [("discovery","عندكم تيشيرتات؟"),("unknown-product","عندكم ديناصور؟")]:
        independent=harness();checked(independent,text,label);h.turns.extend(independent.turns)
    output={"layer":3,"backendDomain":"mocked; values match inspected dev/ai-local-setup.cjs",
            "realPostgreSQL":False,"liveGroq":False,"traces":h.turns}
    Path(path).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    import sys
    export(sys.argv[1])
