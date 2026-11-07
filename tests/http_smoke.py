"""Independent loopback socket check; synthetic data and credentials only."""
import json
import os
import subprocess
import sys
import time

import httpx


def main():
    process=subprocess.Popen([sys.executable,"-m","app.offline_demo","--serve"],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        with httpx.Client(base_url="http://127.0.0.1:8787",trust_env=False,timeout=30) as client:
            for attempt in range(60):
                if process.poll() is not None:
                    raise RuntimeError("Synthetic server exited before startup")
                try:
                    if client.get("/health/live").status_code==200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("Local startup timed out")
            from app.chat.synthetic import identifier
            from app.offline_demo import SCENARIOS
            messages=next(messages for name,messages,_ in SCENARIOS if name=="selection_correction")
            replies=[]
            for index,message in enumerate(messages,1):
                body=dict(businessId=identifier(1,1),customerId=identifier(2,1),
                    conversationId=identifier(3,11),messageId=identifier(9,index),message=message)
                signed=client.post("/demo/context",json=body)
                signed.raise_for_status()
                signed=signed.json()
                response=client.post("/v2/ai/respond",content=signed["body"].encode(),headers=signed["headers"])
                assert response.status_code==200,response.text
                assert response.json()["orderCandidate"] is None
                replies.append(response.json())
            assert replies[2]["requiresReview"] and not replies[3]["requiresReview"]
            assert all(s in replies[3]["reply"] for s in ("285","3","الأبيض","L"))
            assert "275" not in replies[3]["reply"]
            assert client.post("/v2/ai/respond",json=body).status_code==401
            assert client.post("/v1/ai/respond",json={}).status_code==404
            assert client.post("/v2/ai/products/respond",json={}).status_code==404
            assert client.post("/v2/ai/respond",content=b"x"*65537).status_code==413
            print(json.dumps({"transport":"real loopback HTTP","turns":4,"passed":True,
                "authenticationNegative":401,"bodyLimit":413,"retiredRoutes":404,
                "liveBackendVerified":False,"liveGroqVerified":False,"replies":replies},ensure_ascii=False))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__=="__main__":
    main()
