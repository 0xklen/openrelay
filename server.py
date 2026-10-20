#!/usr/bin/env python3
"""OpenRelay — universal uncensored LLM gateway + no-limits agent.

One OpenAI-compatible endpoint in front of any model on any API (OpenAI,
Anthropic, Gemini, DeepSeek, and every OpenAI-compatible host), plus an agent
endpoint that lets the model drive shell/files/network/python with no
restrictions.

Run:
    pip install -r requirements.txt
    cp config.example.yaml config.yaml    # add your endpoints + keys
    uvicorn server:app --host 0.0.0.0 --port 8000
"""
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

import agent as agent_mod
import relay


app = FastAPI(title="OpenRelay", version="1.1.0")


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
    if not relay.pick(target):
        return JSONResponse(status_code=404, content={"error": {"message": f"no model matches '{target}'"}})

    messages = payload.get("messages", [])
    system = payload.get("__system")
    stream = payload.get("stream", False)
    extra = {k: v for k, v in payload.items() if k not in ("model", "messages", "__system")}

    if stream:
        async def gen():
            try:
                async for chunk in relay.stream_chat(messages, target, system=system, **extra):
                    yield chunk
            except Exception as e:
                yield f"data: {{'error': {json.dumps(str(e))}}}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    try:
        content, used = await relay.chat(messages, target, system=system, **extra)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": {"message": str(e)}})
    return {
        "id": "openrelay",
        "object": "chat.completion",
        "model": target,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }


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
