"""OpenRelay core — model registry, routing, persona injection, raw chat.

Shared by the HTTP server (server.py) and the agent loop (agent.py).
Filters nothing, logs no content. Models marked `uncensored: true` pass
through untouched; everything else gets the no-limits persona injected.
"""
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


def build_body(m, messages, system=None, **extra):
    """Upstream request body. An explicit `system` always wins (agent mode);
    otherwise persona/none per model."""
    body = dict(extra)
    body["model"] = m.get("model")
    sys = system if system is not None else system_for(m)
    if sys:
        body["messages"] = [{"role": "system", "content": sys}] + [
            x for x in messages if x.get("role") != "system"
        ]
    else:
        body["messages"] = messages
    if m.get("max_tokens") is not None:
        body.setdefault("max_tokens", m["max_tokens"])
    return body


async def chat(messages, model_name, stream=False, system=None, **extra):
    """Send messages to the first reachable matching model.

    Returns (content_text, model_name) for non-stream. Raises RuntimeError
    if every candidate fails. `system` overrides the persona (agent mode).
    """
    cands = pick(model_name)
    if not cands:
        raise RuntimeError(f"no model matches '{model_name}'")
    last = None
    for m in cands:
        try:
            body = build_body(m, messages, system=system, **extra)
            base = m["base_url"].rstrip("/")
            headers = {"Content-Type": "application/json"}
            if m.get("api_key"):
                headers["Authorization"] = f"Bearer {m['api_key']}"
            timeout = httpx.Timeout(float(m.get("timeout", 300)), connect=30)
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{base}/chat/completions", json=body, headers=headers)
            if r.status_code < 400:
                d = r.json()
                content = d["choices"][0]["message"].get("content") or ""
                return content, m.get("name")
            last = r.text
        except Exception as e:
            last = str(e)
    raise RuntimeError(f"upstream failed: {last}")


load_models()
