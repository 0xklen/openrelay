"""OpenRelay MCP server — expose chat and no-limits task execution to any MCP
client: Hermes, Claude Code, Cursor, Codex, Gemini CLI, and anything else that
speaks MCP over stdio.

Run:
    python mcp_server.py

Register with Hermes:
    hermes mcp add openrelay --command python --args /abs/path/mcp_server.py
(use the absolute path to mcp_server.py, with the openrelay venv's python)
"""
from mcp.server.fastmcp import FastMCP

import agent
import relay

mcp = FastMCP("openrelay")


@mcp.tool()
async def chat(prompt: str, model: str = "local-uncensored", system: str = "") -> str:
    """Send one prompt to any configured model and return the raw answer,
    persona-injected (or raw for uncensored weights). No filtering, no refusal."""
    content, used = await relay.chat(
        [{"role": "user", "content": prompt}], model, system=system or None
    )
    return content


@mcp.tool()
async def task(goal: str, model: str = "local-uncensored", max_steps: int = 24) -> str:
    """Execute a task with no limits — the model drives shell, files, network
    and python until the job is done. No allowlist, no sandbox, no refusal."""
    final, _ = await agent.run_agent(goal, model, max_steps)
    return final


@mcp.tool()
def models() -> str:
    """List every configured model with its provider."""
    if not relay.models:
        return "no models configured"
    return "\n".join(
        f"{m.get('name')} -> {m.get('model')} ({relay.provider(m)})"
        for m in relay.models
    )


if __name__ == "__main__":
    mcp.run()
