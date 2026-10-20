"""Verify the MCP server boots, initializes, exposes chat/task/models tools,
and answers a call. Run from the repo root:
    python test_mcp.py
"""
import asyncio
import os
import sys

CONFIG = "/tmp/openrelay-mcp-test.yaml"
open(CONFIG, "w").write(
    """
models:
  - name: a
    base_url: http://127.0.0.1:1/v1
    model: a-model
  - name: b
    base_url: http://127.0.0.1:1/v1
    model: b-model
    provider: anthropic
"""
)
os.environ["OPENRELAY_CONFIG"] = CONFIG

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env={"OPENRELAY_CONFIG": CONFIG, "PATH": os.environ.get("PATH", "")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("tools:", names)
            assert {"chat", "task", "models"} <= set(names), "missing tools"

            res = await session.call_tool("models", {})
            text = res.content[0].text if res.content else ""
            print("models:", text.strip().replace("\n", " | "))
            assert "a -> a-model" in text and "b -> b-model" in text


asyncio.run(main())
print("PASS: MCP server boots, lists tools, and answers")
