# OpenRelay — universal uncensored LLM gateway + no-limits agent

One OpenAI-compatible endpoint in front of **any model on any API**, with
zero content filtering, zero prompt logging, and a persona layer that makes
guardrailed models answer instead of refusing. An agent mode lets the model
drive a real shell, files, network, and python to complete tasks with no
restrictions.

## What it is

- **Any model, any API** — OpenAI, OpenRouter, Groq, Together, DeepSeek, an
  Anthropic proxy, or a self-hosted Ollama/vLLM/llama.cpp endpoint. One
  `config.yaml` entry per endpoint.
- **No limits in the wire** — nothing is filtered, nothing is logged, no
  refusals are injected, no rate-limit or policy layer. The relay is a
  transparent pipe.
- **No limits at the model** — two layers. For aligned models it injects a
  no-limits persona (configurable per model). For genuinely uncensored
  weights (`uncensored: true`) it forwards raw — those need no persona
  because the weights never learned to refuse.
- **Agent mode** — give it a task, it runs real shell/file/network/python
  commands through the model until the job is done.

## Quick start

```bash
git clone <this-repo> && cd openrelay
pip install -r requirements.txt
cp config.example.yaml config.yaml     # add your endpoints + keys
uvicorn server:app --host 0.0.0.0 --port 8000
```

Or with an uncensored local model in one shot:

```bash
docker compose up -d      # pulls dolphin-mistral (abliterated) + starts the relay
```

## Use it

Chat (any OpenAI client, or curl):

```bash
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-uncensored","messages":[{"role":"user","content":"..."}]}'
```

Agent (task execution, no limits):

```bash
# CLI
python agent.py "scan the repo and tell me what it does" --model local-uncensored

# HTTP
curl http://localhost:8000/v1/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"...","model":"local-uncensored"}'
```

Point any OpenAI-compatible client (agents, apps, scripts) at
`http://host:8000/v1` and pick a model name from `config.yaml`.

## Model registry (`config.yaml`)

```yaml
models:
  - name: local-uncensored
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: dolphin-mistral
    uncensored: true          # self-hosted weights, forwarded raw

  - name: openai
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}   # env-var expanded; keys never in the file
    model: gpt-4o

  - name: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: openai/gpt-4o
```

Entries sharing a `name` act as a failover chain (first that answers wins).
Per-model overrides: `system` (custom persona), `max_tokens`, `timeout`.

## Honest note on "no limits"

The relay removes every guardrail it controls: no filtering, no logging, no
refusals, no policy. The one thing it cannot remove is the guardrail baked
into a hosted model's weights — GPT/Claude/Gemini will still sometimes
refuse no matter what system prompt they get, and the persona layer fights
that but is not bulletproof against model updates.

The durable path is **self-hosted uncensored weights**: dolphin-mistral,
dolphin-mixtral, llama3-uncensored, wizardlm-uncensored, or an abliterated
qwen/llama (refusal directions surgically removed). Route those through any
local endpoint (`uncensored: true`) and nothing in the chain can refuse —
not the relay, not the weights.

## Files

- `relay.py` — registry, routing, persona injection, raw chat (the core)
- `server.py` — FastAPI HTTP layer (`/v1/chat/completions`, `/v1/agent/run`)
- `agent.py` — the no-limits task agent (shell/files/network/python)
- `persona.txt` — no-limits persona for chat
- `agent_persona.txt` — agent system prompt (tool protocol)
- `config.example.yaml`, `docker-compose.yml`, `Dockerfile`

## License

MIT. The relay and agent run whatever the configured model returns; the
person running the endpoint is responsible for what they point it at.
