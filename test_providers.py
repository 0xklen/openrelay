"""Verify the Anthropic and Gemini provider adapters translate correctly.

Runs against a mock that records the request and returns each provider's
native response shape. Run from the repo root:
    python test_providers.py
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

CONFIG = "/tmp/openrelay-provider-test.yaml"
os.environ["OPENRELAY_CONFIG"] = CONFIG
open(CONFIG, "w").write(
    """
models:
  - name: claude
    base_url: http://127.0.0.1:18098
    api_key: anthropic-key
    model: claude-x
    provider: anthropic
  - name: gemini
    base_url: http://127.0.0.1:18098
    api_key: gemini-key
    model: gemini-x
    provider: gemini
"""
)

import relay  # noqa: E402

received = []


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        url = urlparse(self.path)
        received.append(
            {"path": url.path, "query": parse_qs(url.query), "headers": dict(self.headers), "body": body}
        )
        if url.path.endswith("/v1/messages"):
            payload = {"content": [{"type": "text", "text": "anthropic-ok"}]}
        else:
            payload = {"candidates": [{"content": {"parts": [{"text": "gemini-ok"}]}}]}
        p = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(p)))
        self.end_headers()
        self.wfile.write(p)

    def log_message(self, *a):
        pass


def main():
    HTTPServer(("127.0.0.1", 18098), Mock)  # just to bind; serve in thread below
    srv = HTTPServer(("127.0.0.1", 18098), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    async def run():
        a, _ = await relay.chat([{"role": "user", "content": "hi"}], "claude")
        g, _ = await relay.chat([{"role": "user", "content": "hi"}], "gemini")
        return a, g

    a, g = asyncio.run(run())
    assert a == "anthropic-ok", a
    assert g == "gemini-ok", g

    anth, gem = received
    # anthropic: system top-level, x-api-key header, user/assistant messages only
    assert "system" in anth["body"], "anthropic must carry a top-level system"
    assert anth["headers"].get("x-api-key") == "anthropic-key"
    assert all(m["role"] in ("user", "assistant") for m in anth["body"]["messages"])
    # gemini: contents + systemInstruction + ?key= in the query string
    assert "contents" in gem["body"] and "systemInstruction" in gem["body"]
    assert gem["query"].get("key") == ["gemini-key"]
    assert gem["body"]["contents"][0]["parts"][0]["text"] == "hi"

    print("PASS: anthropic + gemini adapters translate and parse correctly")


if __name__ == "__main__":
    main()
