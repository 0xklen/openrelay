<div align="center">

# OpenRelay

### Any model. Any API. No limits.

**One endpoint in front of every model, with no guardrails in the wire — and an agent that does the work.**

[![MIT license](https://img.shields.io/badge/license-MIT-f4c430?style=flat-square)](LICENSE)
[![version](https://img.shields.io/badge/version-1.0.0-5c4ee5?style=flat-square)](https://github.com/0xklen/openrelay/releases)
[![no limits](https://img.shields.io/badge/no%20limits-e63946?style=flat-square)](#what-it-is)
[![docker](https://img.shields.io/badge/docker-compose-2496ed?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)

<img src="assets/logo.png" alt="OpenRelay" width="120" />

<code>uvicorn server:app --host 0.0.0.0 --port 8000</code>

[Quick start](#quick-start) · [How it works](#how-it-works) · [What you can do](#what-you-can-do) · [Agent mode](#agent-mode) · [FAQ](#faq)

</div>

---

OpenRelay is a universal LLM gateway. Point any OpenAI-compatible client at it,
pick a model, and the relay forwards the request to **any model on any API** —
OpenAI, OpenRouter, Groq, Together, DeepSeek, an Anthropic proxy, or a
self-hosted Ollama/vLLM/llama.cpp endpoint — with nothing filtered, nothing
logged, and no refusal layer in between.

Command it with anything. For models that still refuse, OpenRelay injects a
no-limits persona so they answer instead. For genuinely uncensored weights it
forwards raw — and there is no refusal left to trigger, because the weights
never learned one. On top of the relay sits an **agent**: give it a task and it
drives a real shell, the filesystem, the network, and python until the job is
done.

## What it is

- **Any model, any API** — one `config.yaml` entry per endpoint. OpenAI,
  DeepSeek, Groq, Together, OpenRouter, Mistral, xAI, native Anthropic,
  native Gemini, or any OpenAI-compatible self-host (Ollama, vLLM,
  llama.cpp, LM Studio).
- **No limits in the wire** — nothing is filtered, nothing is logged, no
  refusals are injected, no policy or rate-limit layer. The relay is a
  transparent pipe.
- **No limits at the model** — two layers. Guardrailed models get a no-limits
  persona injected (configurable per model). Uncensored weights
  (`uncensored: true`) route raw.
- **Agent mode** — the model executes real shell / file / network / python
  commands until the task is finished.

## Providers

`provider` in `config.yaml` selects the request format. One client request is
translated into each backend's native shape:

| provider     | covers                                                                                 |
| ------------ | -------------------------------------------------------------------------------------- |
| `openai`     | DeepSeek, OpenAI, Groq, Together, OpenRouter, Mistral, xAI, Ollama, vLLM, llama.cpp, LM Studio — any OpenAI-compatible host (default) |
| `anthropic`  | native Anthropic `/v1/messages` (Claude)                                               |
| `gemini`     | native Google `/v1beta/models/...:generateContent`                                     |

DeepSeek and every OpenAI-compatible endpoint work out of the box with
`provider: openai` (the default) — no adapter needed, just a `base_url`.

## Quick start

```bash
git clone https://github.com/0xklen/openrelay && cd openrelay
pip install -r requirements.txt
cp config.example.yaml config.yaml     # add your endpoints + keys
uvicorn server:app --host 0.0.0.0 --port 8000
```

Or spin up an uncensored local model and the relay in one command:

```bash
docker compose up -d      # pulls dolphin-mistral (abliterated) + starts the relay
```

## Use it

Chat — any OpenAI client, or curl:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-uncensored","messages":[{"role":"user","content":"..."}]}'
```

Agent — task execution, no limits:

```bash
# CLI
python agent.py "scan the repo and tell me what it does" --model local-uncensored

# HTTP
curl http://localhost:8000/v1/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"...","model":"local-uncensored"}'
```

Point any OpenAI-compatible client at `http://host:8000/v1` and pick a model
name from `config.yaml`.

## How it works

Your client sends a normal chat request. The relay matches the `model` field to
a registry entry, injects the no-limits persona when the target is guardrailed,
forwards the request to that endpoint, and streams the answer back untouched.
Nothing in the request or response is inspected, filtered, or stored.

```text
client ──► /v1/chat/completions ──► relay (routing + persona) ──► any endpoint
                                   └─► agent: shell · files · network · python
```

For the agent, the model is handed a tool protocol (`[TOOL shell] ... [/TOOL]`)
and its output comes back as tool results. The loop repeats until the model
replies with no tool block — a finished task, not a description of one.

## What you can do

| Target                   | What OpenRelay returns                                          | Requirement                                   |
| ------------------------ | --------------------------------------------------------------- | --------------------------------------------- |
| Any chat model           | Raw completions + streaming, persona-injected or untouched       | An endpoint and key                           |
| Guardrailed models       | No-limits answers via the injected persona                       | Nothing extra — `persona.txt` ships default   |
| Uncensored weights       | Raw answers, no injection, no refusal possible                   | `uncensored: true` in config                  |
| Task execution           | Shell, file read/write, HTTP fetch, python, looped until done    | Agent mode (`agent.py` / `/v1/agent/run`)     |
| Failover                 | Same `name` across endpoints — first that answers wins           | Multiple entries per name                     |
| Local uncensored stack   | Ollama + abliterated model + relay in one `docker compose up`    | Docker                                        |

## Agent mode

```bash
python agent.py "your task" --model local-uncensored --max-steps 24
```

Tools the model can drive:

- `shell` — run a bash command
- `python` — run python3
- `read` — read a file
- `write` — write a file (path on line one, content after)
- `fetch` — HTTP GET a URL

The agent has no restrictions and no refusal. A failed command is just a tool
result — it tries another way until the task is complete.

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

Entries sharing a `name` are a failover chain. Per-model overrides: `system`
(custom persona), `max_tokens`, `timeout`.

## FAQ

<details>
<summary><strong>Does "no limits" survive the model itself?</strong></summary>

The relay removes every guardrail it controls — no filtering, no logging, no
refusals. The one thing it cannot remove is the guardrail baked into a hosted
model's weights: GPT/Claude/Gemini can still refuse regardless of system
prompt, and the persona layer fights that but is not bulletproof against model
updates. The durable path is self-hosted uncensored weights (dolphin-mistral,
dolphin-mixtral, llama3-uncensored, wizardlm-uncensored, or an abliterated
qwen/llama). Route those with `uncensored: true` and nothing in the chain can
refuse — not the relay, not the weights.

</details>

<details>
<summary><strong>Do I need a specific model?</strong></summary>

No. Any OpenAI-compatible endpoint works, including local servers that need no
key and no account. Uncensored local weights are the only way to remove model
refusals entirely.

</details>

<details>
<summary><strong>What does the agent actually run?</strong></summary>

Whatever the model emits in a tool block, executed as the user running the
process — bash, python, file writes, HTTP. No allowlist, no sandbox.

</details>

<details>
<summary><strong>Where do keys live?</strong></summary>

`config.yaml` uses `${ENV_VAR}` so keys stay in your shell environment and
never touch the file or the repo.

</details>

## MCP — use it from any agent

OpenRelay ships an MCP server, so Hermes, Claude Code, Cursor, Codex, Gemini
CLI and any MCP-speaking agent can call it directly as tools.

```bash
python mcp_server.py            # stdio MCP server
```

Register with Hermes:

```bash
hermes mcp add openrelay --command python --args /absolute/path/openrelay/mcp_server.py
```

Three tools: `chat` (raw answer, persona-injected), `task` (no-limits agent
execution), `models` (list). Restart the agent and it can command any
configured model — or hand it a task and it runs shell/files/network/python
until done.

## Files

- `relay.py` — registry, routing, provider adapters, persona, raw chat (core)
- `server.py` — FastAPI HTTP layer (`/v1/chat/completions`, `/v1/agent/run`)
- `mcp_server.py` — MCP server (`chat`, `task`, `models`) for any agent
- `agent.py` — the no-limits task agent (shell/files/network/python)
- `persona.txt` — no-limits persona for chat
- `agent_persona.txt` — agent system prompt (tool protocol)
- `config.example.yaml`, `docker-compose.yml`, `Dockerfile`, `test_e2e.py`

## License

[MIT](LICENSE)
