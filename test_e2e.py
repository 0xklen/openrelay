"""End-to-end verification against a mock upstream.

Proves three things:
  1. uncensored models route raw (no persona injected)
  2. guardrailed models get the no-limits persona injected as the system message
  3. the agent loop executes a real shell command and finishes

Run from the repo root:
    python test_e2e.py
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CONFIG = "/tmp/openrelay-test-config.yaml"
os.environ["OPENRELAY_CONFIG"] = CONFIG

# point the relay at the mock
open(CONFIG, "w").write(
    """
models:
  - name: uncensored
    base_url: http://127.0.0.1:18099/v1
    api_key: x
    model: raw-model
    uncensored: true
  - name: aligned
    base_url: http://127.0.0.1:18099/v1
    api_key: x
    model: gpt-model
"""
)

import relay  # noqa: E402  (reads CONFIG + persona.txt)
import agent  # noqa: E402

received = []


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        received.append(body)
        msgs = body.get("messages", [])
        has_tool_result = any("Tool results:" in (m.get("content") or "") for m in msgs)
        text = "task complete: openrelay-live" if has_tool_result else "[TOOL shell]\necho openrelay-live\n[/TOOL]"
        payload = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": text}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def main():
    srv = HTTPServer(("127.0.0.1", 18099), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    async def run():
        # 1. raw routing for uncensored
        await relay.chat([{"role": "user", "content": "hi"}], "uncensored")
        # 2. persona injection for aligned
        await relay.chat([{"role": "user", "content": "hi"}], "aligned")
        # 3. agent loop
        final, log = await agent.run_agent("run a command", "aligned", max_steps=4)

        unc = received[0]
        aln = received[1]
        assert all(m.get("role") != "system" for m in unc["messages"]), "uncensored must route raw"
        assert aln["messages"][0]["role"] == "system", "aligned must get a system message"
        assert aln["messages"][0]["content"] == relay.persona(), "persona must be injected"

        tool_outputs = [e["output"] for e in log if e.get("role") == "tool"]
        assert any("openrelay-live" in o for o in tool_outputs), "agent must run the shell command"
        assert final == "task complete: openrelay-live", "agent must finish"
        return tool_outputs

    outs = asyncio.run(run())
    print("PASS: raw routing, persona injection, and agent shell execution all verified")
    print("shell output captured:", repr(outs[0]))


if __name__ == "__main__":
    main()
