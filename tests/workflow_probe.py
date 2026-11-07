"""Test-only observation of the canonical engine; never imported by production."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch

from app import api
from app.offline_demo import OfflineHarness
from app.pipeline.evidence_guard import validate_final_response
from app.schemas.backend import Product, ProductVariant, Page, AuthorizedHistoryPage


def product_fixture():
    """Synthetic values matching Backend dev/ai-local-setup.cjs, never SQL data."""
    from copy import deepcopy
    from app.chat.synthetic import catalog
    products=deepcopy(catalog())
    primary,linen=products
    primary.update(name="تيشيرت قطن",basePrice="250.00",
                   options={"Color":["Black","White"],"Size":["M","L"]},
                   attributes={"material":"قطن"},colorOptionName="Color")
    primary["variants"]=[primary["variants"][i] for i in (1,0,2)]
    for variant,price,stock in zip(primary["variants"],("275.00",None,"290.00"),(7,0,3)):
        variant.update(productId=primary["id"],unitPrice=price,
                       effectivePrice=price if price is not None else "250.00",stockQuantity=stock)
        variant["optionValues"]={key.title():value for key,value in variant["optionValues"].items()}
    primary["variantsPagination"].update(totalCount=3,hasMore=False,nextOffset=None)
    linen.update(name="قميص كتان",basePrice="350.00",isSellable=True)
    linen["variants"][0].update(productId=linen["id"],unitPrice=None,effectivePrice="350.00")
    from tests.test_unified_acceptance import contract_product
    primary["images"]=deepcopy(contract_product()["images"])
    for image in primary["images"]:
        image["productId"]=primary["id"]
    return products


def turn_trace(body, turn, history_status):
    from dataclasses import asdict
    execution=turn.execution
    plan=execution.plan
    return {
        "messageId":str(body.messageId),
        "understanding":{"act":turn.understanding.meaning.act,
                         "search":turn.understanding.meaning.search,
                         "options":dict(turn.understanding.inquiry.option_values),
                         "quantity":turn.understanding.meaning.quantity,
                         "reportedSource":turn.understanding.source},
        "historyStatus":history_status,
        "productIds":[str(p.product_id) for p in plan.products],
        "selectedVariantId":str(plan.selected_variant_id) if plan.selected_variant_id else None,
        "matchingVariantIds":[str(v) for v in plan.matching_variant_ids],
        "quantity":plan.requested_quantity,
        "facts":[{"productId":str(v.product_id),"variantId":str(v.variant_id),
                  "options":dict(v.option_values),
                  "effectivePrice":format(v.effective_price,".2f") if v.effective_price is not None else None,
                  "inventory":v.inventory.value,"recordedQuantity":v.recorded_quantity,
                  "source":{"tool":v.source.tool,"envelopeIndex":v.source.envelope_index,"path":v.source.path}}
                 for v in plan.variants if v.variant_id in plan.matching_variant_ids],
        "typedEvidence":[{"tool":out.envelope.tool,"model":type(out.envelope.data).__name__}
                         for out in execution.retrieval.evidence if out.envelope is not None],
        "catalogCoverage":plan.catalog_coverage.value,
        "limitations":list(plan.limitations),
        "reportedGenerationSource":execution.generation.source,
        "fallbackReason":execution.generation.fallback_reason,
        "finalGuardPassed":validate_final_response(plan,turn.response),
        "response":turn.response.model_dump(mode="json"),
        "ordersEnabled":execution.order_extension.enabled,
        "provisionalIntent":json.loads(json.dumps(asdict(execution.order_extension.purchase_intent),default=str)) if execution.order_extension.purchase_intent else None,
        "orderDraft":json.loads(json.dumps(asdict(execution.order_extension.draft),default=str)) if execution.order_extension.draft else None,
        "missingFacts":list(plan.missing_facts),
        "understandingFallback":turn.understanding.fallback,
        "liveGroq":False,
    }


@contextmanager
def observe_turns(sink):
    original=api.execute_conversation
    async def observed(body,*args,**kwargs):
        result=await original(body,*args,**kwargs)
        sink(turn_trace(body,*result))
        return result
    with patch.object(api,"execute_conversation",observed):
        yield


class TracedHarness(OfflineHarness):
    """Synthetic authenticated callback traces; secrets/headers are never saved."""
    def __init__(self,**settings):
        self.tool_trace=[]
        self.turns=[]
        super().__init__(**settings)

    async def _backend(self,request):
        wire=json.loads(request.content)
        entry={"tool":wire["tool"],"arguments":wire["arguments"],
               "layer":"synthetic_authenticated_Backend_HTTP_transport"}
        self.tool_trace.append(entry)
        try:
            response=await super()._backend(request)
            if response.status_code==200 and wire["tool"] in {"get_products","get_product_details"}:
                import httpx
                value=response.json()
                products=value["data"]["items"] if wire["tool"]=="get_products" else [value["data"]]
                for product in products:
                    if len(product["variants"])>20:
                        count=len(product["variants"])
                        product["variants"]=product["variants"][:20]
                        product["variantsPagination"]={"limit":20,"offset":0,"totalCount":count,
                                                       "hasMore":True,"nextOffset":20}
                response=httpx.Response(200,json=value)
            entry["httpStatus"]=response.status_code
            entry["schemaValid"]=False
            if response.status_code==200:
                models={"get_products":Page[Product],"get_product_details":Product,
                        "get_product_variants":Page[ProductVariant],"get_variant_details":ProductVariant,
                        "get_conversation_history":AuthorizedHistoryPage}
                try:
                    models[wire["tool"]].model_validate(response.json()["data"])
                    entry["schemaValid"]=True
                except (ValueError,KeyError,TypeError):
                    pass
            return response
        except Exception:
            entry.update(httpStatus=None,schemaValid=False,transportFailure=True)
            raise

    def traced_send(self,message,*,label="fixture",**body_options):
        body=self.body(message,**body_options)
        start=len(self.tool_trace)
        captured=[]
        with observe_turns(captured.append):
            result=self.send(body)
        trace={"case":label,"layer":"FastAPI_TestClient_with_synthetic_Backend_and_Groq",
               "httpStatus":result.status_code,"toolCallbacks":self.tool_trace[start:],
               "execution":captured[-1] if captured else None,"liveBackend":False,"realPersistence":False}
        self.turns.append(trace)
        return result,trace


def serve(trace_file):
    """Real HTTP, same app.local factory; observe only synthetic test turns."""
    import os
    import uvicorn
    from app.local import create_local_application
    target=Path(trace_file)
    def sink(value):
        with target.open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(value,ensure_ascii=False)+"\n")
    with observe_turns(sink):
        uvicorn.run(create_local_application(),host="127.0.0.1",port=int(os.environ["AI_LOCAL_PORT"]),
                    proxy_headers=False,access_log=False,log_level="error")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-file",required=True)
    serve(parser.parse_args().trace_file)
