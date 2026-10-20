#!/usr/bin/env python3
"""OpenRelay — universal uncensored LLM gateway + no-limits agent.

One OpenAI-compatible endpoint in front of any model on any API, plus an
agent endpoint that lets the model drive shell/files/network/python to
complete tasks with no restrictions.

Run:
    pip install -r requirements.txt
    cp config.example.yaml config.yaml    # add your endpoints + keys
    uvicorn server:app --host 0.0.0.0 --port 8000
"""
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

import agent as agent_mod
import relay


app = FastAPI(title="OpenRelay", version="1.0.0")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "models": len(relay.models)}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": m.get("model") or m.get("name"),
                "object": "model",
                "owned_by": m.get("name"),
            }
            for m in relay.models
        ],
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    payload = await request.json()
    target = payload.get("model", "")
    cands = relay.pick(target)
    if not cands:
        return JSONResponse(status_code=404, content={"error": {"message": f"no model matches '{target}'"}})

    stream = payload.get("stream", False)
    system = payload.get("__system")
    messages = payload.get("messages", [])
    extra = {k: v for k, v in payload.items() if k not in ("model", "messages", "__system")}
    last_err = None

    for m in cands:
        try:
            body = relay.build_body(m, messages, system=system, **extra)
            base = m["base_url"].rstrip("/")
            headers = {"Content-Type": "application/json"}
            if m.get("api_key"):
                headers["Authorization"] = f"Bearer {m['api_key']}"
            timeout = httpx.Timeout(float(m.get("timeout", 300)), connect=30)

            if stream:
                async def gen():
                    client = httpx.AsyncClient(timeout=timeout)
                    try:
                        async with client.stream(
                            "POST", f"{base}/chat/completions",
                            json=body, headers=headers,
                        ) as r:
                            if r.status_code >= 400:
                                err = (await r.aread()).decode(errors="replace")
                                yield f'data: {{"error": {err!r}}}\n\n'
                                yield "data: [DONE]\n\n"
                                return
                            async for chunk in r.aiter_bytes():
                                yield chunk
                    finally:
                        await client.aclose()

                return StreamingResponse(gen(), media_type="text/event-stream")

            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{base}/chat/completions", json=body, headers=headers)
            if r.status_code < 400:
                return JSONResponse(r.json(), status_code=r.status_code)
            last_err = r.text
        except Exception as e:
            last_err = str(e)

    return JSONResponse(status_code=502, content={"error": {"message": f"upstream failed: {last_err}"}})


@app.post("/v1/agent/run")
async def agent_run(request: Request):
    payload = await request.json()
    task = payload.get("task", "")
    if not task:
        return JSONResponse(status_code=400, content={"error": {"message": "task is required"}})
    model = payload.get("model", "local-uncensored")
    max_steps = int(payload.get("max_steps", agent_mod.MAX_STEPS))
    try:
        final, log = await agent_mod.run_agent(task, model, max_steps)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": {"message": str(e)}})
    return {"result": final, "steps": log}
