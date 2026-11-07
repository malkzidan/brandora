"""Local-only startup of the actual release launcher using throwaway credentials."""
import os
import subprocess
import sys
import time
import json

import httpx


def main():
    from app.offline_demo import OfflineHarness
    h=OfflineHarness()
    env={**os.environ,"APP_ENV":"staging","AI_PROVIDER":"groq","AI_INTEGRATION_ENABLED":"true",
         "GROQ_API_KEY":"synthetic-not-a-real-provider-key","AI_SERVICE_TOKEN":h.settings.ai_service_token,
         "BACKEND_SERVICE_TOKEN":h.settings.backend_service_token,"BACKEND_BASE_URL":"https://synthetic.invalid",
         "BACKEND_CONTEXT_PUBLIC_KEY":h.settings.backend_context_public_key,
         "TRUSTED_PROXY_CIDRS":"127.0.0.1/32","PORT":"8788"}
    process=subprocess.Popen([sys.executable,"-m","app.server"],env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        with httpx.Client(base_url="http://127.0.0.1:8788",trust_env=False,timeout=10) as client:
            for attempt in range(60):
                if process.poll() is not None:
                    raise RuntimeError("Release launcher refused configured local startup")
                try:
                    if client.get("/ready").status_code==200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("Release startup timed out")
            raw,headers=h.encode(h.body("hi"))
            assert client.post("/v2/ai/respond",content=raw,headers=headers).status_code==400
            response=client.post("/v2/ai/respond",content=raw,headers={**headers,"X-Forwarded-Proto":"https"})
            assert response.status_code==200,response.text
            assert response.json()["orderCandidate"] is None
            assert client.post("/v1/ai/respond",json={}).status_code==404
            assert client.post("/demo/context",json={}).status_code==404
            print(json.dumps({"launcher":"python -m app.server","port":8788,"passed":True,
                "httpsRequired":400,"signedGreeting":200,"retiredRoutes":404,"demoRoute":404,
                "liveBackendVerified":False,"liveGroqVerified":False}))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__=="__main__":
    main()
