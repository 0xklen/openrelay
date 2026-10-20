"""OpenRelay core — model registry, routing, persona injection, raw chat.

Shared by the HTTP server (server.py), the agent loop (agent.py), and the MCP
server (mcp_server.py). Filters nothing, logs no content.

Provider adapters translate one OpenAI-compatible request into the native
format of each backend, so "any model" is literal:

    openai      OpenAI-compatible (DeepSeek, Groq, Together, OpenRouter,
                Mistral, xAI, Ollama, vLLM, llama.cpp, LM Studio, ...)
    anthropic   native Anthropic /v1/messages
    gemini      native Google /v1beta/models/...:generateContent

Models marked `uncensored: true` route raw; everything else gets the
no-limits persona injected unless the caller passes an explicit `system`.
"""
import json
import os
import re

import httpx
import yaml

CONFIG_PATH = os.environ.get("OPENRELAY_CONFIG", "config.yaml")
PERSONA_PATH = os.environ.get("OPENRELAY_PERSONA", "persona.txt")

models = []


def _interp(s: str) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), s)


def load_models():
    global models
    cfg = yaml.safe_load(_interp(open(CONFIG_PATH).read())) or {}
    models = cfg.get("models", []) or []


def persona() -> str:
    return open(PERSONA_PATH).read().strip()


def _matches(m, n) -> bool:
    return m.get("name") == n or m.get("model") == n


def pick(name):
    """All registry entries a client model field can hit, in order (failover)."""
    return [m for m in models if _matches(m, name)]


def system_for(m) -> str:
    if m.get("system"):
        return m["system"]
    if m.get("uncensored"):
        return ""
    return persona()


def provider(m) -> str:
    return (m.get("provider") or "openai").lower()


# ---------------------------------------------------------------- adapters


def _openai_body(m, messages, system, extra):
    body = dict(extra)
    body["model"] = m.get("model")
    if m.get("max_tokens") is not None:
        body.setdefault("max_tokens", m["max_tokens"])
    if system:
        body["messages"] = [{"role": "system", "content": system}] + [
            x for x in messages if x.get("role") != "system"
        ]
    else:
        body["messages"] = messages
    return body


def _anthropic_body(m, messages, system, extra):
    body = {
        "model": m.get("model"),
        "max_tokens": extra.get("max_tokens", m.get("max_tokens", 4096)),
    }
    if system:
        body["system"] = system
    body["messages"] = [
        {"role": x["role"], "content": x.get("content", "")}
        for x in messages
        if x.get("role") in ("user", "assistant")
    ]
    return body


def _gemini_body(m, messages, system, extra):
    contents = [
        {
            "role": "model" if x.get("role") == "assistant" else "user",
            "parts": [{"text": x.get("content", "")}],
        }
        for x in messages
    ]
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if m.get("max_tokens") is not None:
        body.setdefault("generationConfig", {})["maxOutputTokens"] = m["max_tokens"]
    return body


def _plan(m, messages, system, extra):
    """(url, headers, body) for the model's provider."""
    prov = provider(m)
    base = m["base_url"].rstrip("/")
    headers = {"Content-Type": "application/json"}
    key = m.get("api_key") or ""

    if prov == "anthropic":
        body = _anthropic_body(m, messages, system, extra)
        url = f"{base}/v1/messages"
        if key:
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
    elif prov == "gemini":
        body = _gemini_body(m, messages, system, extra)
        url = f"{base}/v1beta/models/{m.get('model')}:generateContent"
        if key:
            url += f"?key={key}"
    else:
        body = _openai_body(m, messages, system, extra)
        url = f"{base}/chat/completions"
        if key:
            headers["Authorization"] = f"Bearer {key}"
    return url, headers, body


def _parse(r, prov):
    d = r.json()
    if prov == "anthropic":
        return "".join(p.get("text", "") for p in d.get("content", []) if p.get("type") == "text")
    if prov == "gemini":
        try:
            return "".join(
                p.get("text", "")
                for c in d.get("candidates", [])
                for p in c.get("content", {}).get("parts", [])
            )
        except Exception:
            return ""
    return d["choices"][0]["message"].get("content") or ""


async def chat(messages, model_name, system=None, **extra):
    """Non-stream chat. Returns (content, model_name_used). Raises on total failure."""
    cands = pick(model_name)
    if not cands:
        raise RuntimeError(f"no model matches '{model_name}'")
    last = None
    for m in cands:
        sys = system if system is not None else system_for(m)
        try:
            url, headers, body = _plan(m, messages, sys, extra)
            timeout = httpx.Timeout(float(m.get("timeout", 300)), connect=30)
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(url, json=body, headers=headers)
            if r.status_code < 400:
                return _parse(r, provider(m)), m.get("name")
            last = r.text
        except Exception as e:
            last = str(e)
    raise RuntimeError(f"upstream failed: {last}")


async def stream_chat(messages, model_name, system=None, **extra):
    """SSE stream for OpenAI-compatible backends; other providers yield the
    non-stream result as a single chunk so every client path still works."""
    cands = pick(model_name)
    if not cands:
        raise RuntimeError(f"no model matches '{model_name}'")
    m = cands[0]

    if provider(m) != "openai":
        content, _ = await chat(messages, model_name, system=system, **extra)
        yield f"data: {json.dumps({'choices': [{'delta': {'content': content}}]})}\n\n"
        yield "data: [DONE]\n\n"
        return

    sys = system if system is not None else system_for(m)
    url, headers, body = _plan(m, messages, sys, extra)
    timeout = httpx.Timeout(float(m.get("timeout", 300)), connect=30)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        async with client.stream("POST", url, json=body, headers=headers) as r:
            if r.status_code >= 400:
                err = (await r.aread()).decode(errors="replace")
                yield f"data: {{'error': {json.dumps(err)}}}\n\n"
                yield "data: [DONE]\n\n"
                return
            async for chunk in r.aiter_bytes():
                yield chunk
    finally:
        await client.aclose()


load_models()
