"""Claude Code on the hub (harness.py).

Two halves, both set up by the plugin in connectors/claude-code/:

    in      a channel: an MCP server Claude Code starts with the session (`jev-interaction channel`, this module's
            `main`). It pushes the user's spoken words into the session as <channel source="jev" task="3"> events, gives
            Claude a `say` tool for words meant to be heard, and relays a permission prompt and its answer.
            https://code.claude.com/docs/en/channels-reference
    out     hooks: Claude Code posts its own events (a prompt typed, a tool about to run, the turn ended) to the call
            server, which reads them here (`events`).

What Claude Code cannot do from outside: a turn that is running cannot be interrupted, and words pushed while it runs
wait for it to end. So a "steer" is a turn of its own, and a "cancel" only drops the task on the voice's side.

The channel speaks MCP over stdio by hand (newline-delimited JSON-RPC): a handful of messages, and nothing to install
beside this package.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading

HARNESS = "Claude Code"
SERVER = "jev"                   # the MCP server's key in the plugin: the `source` of every <channel> event

OURS = re.compile(r'<channel source="[^"]*\b' + SERVER + r'"')     # a prompt that is one of this channel's events

INSTRUCTIONS = (
    'Events from this server, tagged <channel ... task="N">, are the user speaking to you through their voice companion: '
    "their own words, heard and written down, not typed. Take them as you would a prompt of theirs. The user is "
    "listening, not reading: when the work a task asks for is done, or you have something to tell them about it, call "
    "the `say` tool with that task number and what to say out loud: a sentence or two in plain spoken words, what "
    "matters and nothing else, no code, no paths, no lists. The details stay on the screen as usual.")

SAY = {"name": "say", "description": "Say something to the user out loud through their voice companion: the outcome of "
       "what they asked for by voice, or something they need to know now. A sentence or two of plain spoken words.",
       "inputSchema": {"type": "object", "required": ["text"], "properties": {
           "text": {"type": "string", "description": "what to say, as it should be heard"},
           "task": {"type": "string", "description": "the task number from the <channel> tag this answers, if any"}}}}


# ---------------------------------------------------------------------- out: hooks -> the hub's events
def _doing(tool: str, given: dict) -> str:
    """A tool call in a few words, for the voice to say how far the work has got."""
    given = given if isinstance(given, dict) else {}
    name = os.path.basename(str(given.get("file_path") or given.get("notebook_path") or given.get("path") or ""))
    if tool == "Bash":
        return f"running: {given.get('description') or str(given.get('command') or '')[:80]}"
    if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return f"editing {name}" if name else "editing a file"
    if tool == "Read":
        return f"reading {name}" if name else "reading"
    if tool in ("Grep", "Glob"):
        return f"searching for {str(given.get('pattern') or '')[:60]}"
    if tool in ("Task", "Agent"):
        return f"a helper is on: {given.get('description') or 'part of it'}"
    if tool in ("WebSearch", "WebFetch"):
        return "looking something up on the web"
    return f"using {tool}"


def events(hook: dict) -> list[dict]:
    """One hook payload from Claude Code as the hub's events (harness.py)."""
    name = hook.get("hook_event_name")
    if name == "UserPromptSubmit":
        prompt = str(hook.get("prompt") or "")
        return [{"type": "turn_start", "text": prompt, "ours": bool(OURS.search(prompt))}]
    if name == "PreToolUse":                      # a new tool call: whatever was asked about the one before is settled
        if str(hook.get("tool_name") or "").endswith("__say"):
            return []
        return [{"type": "tool_done"}, {"type": "progress", "text": _doing(str(hook.get("tool_name") or ""), hook.get("tool_input") or {})}]
    if name in ("PostToolUse", "PostToolUseFailure", "PermissionDenied"):
        return [{"type": "tool_done"}]
    if name == "Stop":
        return [{"type": "turn_end", "text": str(hook.get("last_assistant_message") or "")}]
    if name == "StopFailure":                     # the turn broke off on an error of the model's service, not on the work
        why = str(hook.get("last_assistant_message") or hook.get("error_details") or hook.get("error") or "an error")
        return [{"type": "turn_end", "text": "", "error": why}]
    return []


def asks(params: dict) -> dict:
    """A permission prompt relayed by Claude Code, as the hub's `ask`."""
    what, tool, shown = params.get("description") or "", params.get("tool_name") or "a tool", params.get("input_preview") or ""
    text = f"{HARNESS} asks to use {tool}: {what}" + (f" ({shown[:160]})" if shown and shown != what else "")
    return {"type": "ask", "id": params.get("request_id") or "", "text": text}


# ---------------------------------------------------------------------- in: the channel process
class Channel:
    def __init__(self, url: str, cwd: str, out=None):
        self.url, self.cwd = url, cwd
        self.out = out or sys.stdout
        self.hub = None                       # the socket to the call server, while it is up
        self._lock = threading.Lock()

    def write(self, message: dict) -> None:
        with self._lock:
            self.out.write(json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n")
            self.out.flush()

    async def to_hub(self, event: dict) -> bool:
        if self.hub is None:
            return False
        try:
            await self.hub.send(json.dumps(event, ensure_ascii=False))
            return True
        except Exception:  # noqa: BLE001 - the call server went away; the loop below reconnects
            return False

    # ---- Claude Code -> us
    async def on_mcp(self, m: dict) -> None:
        method, mid, params = m.get("method"), m.get("id"), m.get("params") or {}
        if method == "initialize":
            self.write({"id": mid, "result": {
                "protocolVersion": params.get("protocolVersion") or "2025-06-18",
                "capabilities": {"experimental": {"claude/channel": {}, "claude/channel/permission": {}}, "tools": {}},
                "serverInfo": {"name": SERVER, "version": "0.1.0"}, "instructions": INSTRUCTIONS}})
        elif method == "ping":
            self.write({"id": mid, "result": {}})
        elif method == "tools/list":
            self.write({"id": mid, "result": {"tools": [SAY]}})
        elif method == "tools/call":
            args = params.get("arguments") or {}
            sent = params.get("name") == "say" and await self.to_hub({"type": "say", "task": str(args.get("task") or ""),
                                                                      "text": str(args.get("text") or "")})
            text = "Said." if sent else "The voice companion is not running: nothing was said."
            self.write({"id": mid, "result": {"content": [{"type": "text", "text": text}]}})
        elif method == "notifications/claude/channel/permission_request":
            await self.to_hub(asks(params))
        elif mid is not None and method:          # a request this server has no answer to
            self.write({"id": mid, "error": {"code": -32601, "message": f"no such method: {method}"}})

    # ---- the hub -> Claude Code
    def on_hub(self, e: dict) -> None:
        kind = e.get("type")
        if kind in ("prompt", "steer") and e.get("text"):
            self.write({"method": "notifications/claude/channel",
                        "params": {"content": e["text"], "meta": {"task": str(e.get("task") or "")}}})
        elif kind == "answer" and e.get("behavior") in ("allow", "deny"):
            self.write({"method": "notifications/claude/channel/permission",
                        "params": {"request_id": e.get("id") or "", "behavior": e["behavior"]}})
        # "cancel": a running turn cannot be stopped from outside Claude Code

    async def hub_loop(self) -> None:
        """Stay on the call server's hub; it may start after Claude Code does, or be restarted."""
        import websockets
        while True:
            try:
                async with websockets.connect(self.url, max_size=None) as ws:
                    self.hub = ws
                    await ws.send(json.dumps({"type": "hello", "harness": HARNESS, "cwd": self.cwd, "steer": "turn"}))
                    async for raw in ws:
                        self.on_hub(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - not up yet, or gone: try again shortly
                pass
            finally:
                self.hub = None
            await asyncio.sleep(2.0)

    async def run(self, stdin=None) -> None:
        loop, lines = asyncio.get_running_loop(), asyncio.Queue()
        stdin = stdin or sys.stdin

        def read():                               # stdin on a thread: a pipe from Claude Code, closed when the session ends
            for line in stdin:
                loop.call_soon_threadsafe(lines.put_nowait, line)
            loop.call_soon_threadsafe(lines.put_nowait, None)
        threading.Thread(target=read, daemon=True).start()
        hub = loop.create_task(self.hub_loop())
        try:
            while (line := await lines.get()) is not None:
                if line.strip():
                    try:
                        await self.on_mcp(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        finally:
            hub.cancel()


def main(url: str | None = None, cwd: str | None = None) -> int:
    url = url or os.getenv("JEV_INTERACTION_HUB") or "ws://127.0.0.1:8080/harness/ws"
    asyncio.run(Channel(url, cwd or os.getenv("CLAUDE_PROJECT_DIR") or os.getcwd()).run())
    return 0
