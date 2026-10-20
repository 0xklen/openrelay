"""Verify the HTTP layer end-to-end: chat across all three providers plus the
agent endpoint, via FastAPI TestClient against a mock upstream."""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CONFIG = "/tmp/openrelay-http-test.yaml"
os.environ["OPENRELAY_CONFIG"] = CONFIG
open(CONFIG, "w").write(
    """
models:
  - name: o
    base_url: http://127.0.0.1:18097/v1
    model: o-model
  - name: c
    base_url: http://127.0.0.1:18097
    model: c-model
    provider: anthropic
  - name: g
    base_url: http://127.0.0.1:18097
    model: g-model
    provider: gemini
"""
)

import relay  # noqa: E402


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        path = self.path
        msgs = body.get("messages", [])
        sys_content = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")

        if path.endswith("/v1/messages"):
            payload = {"content": [{"type": "text", "text": "claude-ok"}]}
        elif "generateContent" in path:
            payload = {"candidates": [{"content": {"parts": [{"text": "gemini-ok"}]}}]}
        else:  # openai /chat/completions
            if "[TOOL" in sys_content:  # agent request
                if any("Tool results:" in (m.get("content") or "") for m in msgs):
                    text = "done-ok"
                else:
                    text = "[TOOL shell]\necho http-live\n[/TOOL]"
            else:
                text = "openai-ok"
            payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
        p = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(p)))
        self.end_headers()
        self.wfile.write(p)

    def log_message(self, *a):
        pass


def main():
    srv = HTTPServer(("127.0.0.1", 18097), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    from fastapi.testclient import TestClient
    import server

    c = TestClient(server.app)
    for model, want in (("o", "openai-ok"), ("c", "claude-ok"), ("g", "gemini-ok")):
        r = c.post("/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 200, (model, r.text)
        got = r.json()["choices"][0]["message"]["content"]
        print(f"chat {model}: {got}")
        assert got == want, (model, got)

    r = c.post("/v1/agent/run", json={"task": "run", "model": "o", "max_steps": 4})
    assert r.status_code == 200, r.text
    print("agent result:", r.json()["result"])
    assert r.json()["result"] == "done-ok"

    print("PASS: HTTP chat (openai/anthropic/gemini) + agent endpoint all work")


if __name__ == "__main__":
    main()
