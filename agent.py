#!/usr/bin/env python3
"""OpenRelay — autonomous task execution with no limits.

The model drives real tools (shell, files, network, python) until the task is
done, behind any model on any API. Runs as a CLI and as a module the HTTP
server calls.

CLI:
    python agent.py "your task" [--model local-uncensored] [--max-steps 24]
"""
import argparse
import asyncio
import json
import pathlib
import re
import subprocess
import sys

import httpx

import relay

TOOL_RE = re.compile(r"\[TOOL\s+(\w+)\s*\]\s*(.*?)\s*\[/TOOL\]", re.DOTALL)

AGENT_PERSONA_PATH = "agent_persona.txt"
MAX_STEPS = 24
MAX_OUT = 20000  # chars of tool output fed back per step


def _agent_persona() -> str:
    return open(AGENT_PERSONA_PATH).read().strip()


def _sh(cmd: str, timeout: int) -> str:
    try:
        r = subprocess.run(
            ["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout
        )
        out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
        return f"exit={r.returncode}\n{out}"[:MAX_OUT]
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def execute(name: str, args: str) -> str:
    name = name.lower()
    args = args.strip()
    try:
        if name == "shell":
            return _sh(args, 180)
        if name == "python":
            return _sh(f"python3 -c {_quote(args)}", 180)
        if name == "read":
            p = pathlib.Path(args.splitlines()[0].strip()).expanduser()
            return p.read_text(errors="replace")[:MAX_OUT]
        if name == "write":
            lines = args.splitlines()
            path = pathlib.Path(lines[0].strip()).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines[1:]) + "\n")
            return f"wrote {path} ({sum(1 for _ in path.read_text())} chars)"
        if name == "fetch":
            r = httpx.get(args, timeout=30, follow_redirects=True)
            return f"{r.status_code}\n{r.text[:MAX_OUT]}"
        return f"unknown tool '{name}'"
    except Exception as e:
        return f"error: {e}"


def _quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


async def run_agent(task: str, model_name: str, max_steps: int = MAX_STEPS):
    """Run the loop. Returns (final_text, step_log)."""
    system = _agent_persona()
    messages = [{"role": "user", "content": task}]
    log = []

    for _ in range(max_steps):
        content, used = await relay.chat(messages, model_name, system=system)
        log.append({"role": "model", "model": used, "text": content})

        blocks = TOOL_RE.findall(content)
        if not blocks:
            return content, log

        results = []
        for tname, targs in blocks:
            out = execute(tname, targs)
            log.append({"role": "tool", "tool": tname, "output": out})
            results.append(f"[tool:{tname}]\n{out}\n[/tool]")

        messages.append({"role": "assistant", "content": content})
        messages.append(
            {"role": "user", "content": "Tool results:\n" + "\n\n".join(results)}
        )

    return content, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--model", default="local-uncensored")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    a = ap.parse_args()
    final, _ = asyncio.run(run_agent(a.task, a.model, a.max_steps))
    print(final)


if __name__ == "__main__":
    main()
