"""Codex's own model as the responder: the harness the user already has, on the account they are already signed in to,
with no key of ours.

One `codex app-server` process is kept open for the call, speaking its JSON-RPC on stdio: a thread on the model the
user chose for talking (JEV_FAST_MODEL: a fast one from Codex's own list), a turn per reply, the text streamed back as
it is written. The thread keeps the conversation itself, so each reply sends only what it has not heard yet:
everything after the agent's last line. A persona put on the line is a new thread on the same process.

It runs with no plugins, no hooks, no apps and no MCP servers (it only talks, and the hooks of our own plugin must not
fire for it), read-only, asking for nothing. The session the user works in keeps its own model.

Checked with a signed-in Codex (codex-cli 0.163) on a fast model: about 1.2 s to the first words of a reply. The first
reply of a process takes about 10 s (it connects): the greeting of a call pays for it. `warm=True` asks for a reply and
throws it away at once, for whoever makes the responder before the call.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil

from .claude_cli import SPOKEN, ClaudeCodeResponder

PLACES = ["codex", "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
          "/Applications/Codex.app/Contents/Resources/codex", "~/.local/bin/codex", "/opt/homebrew/bin/codex", "/usr/local/bin/codex"]
# It only talks: nothing of the coding agent is left on. With its tools there it takes the user's request for its own
# work (seen on a first run: asked "which folder?" where it should have handed the task off).
OFF = ["plugins", "hooks", "apps", "goals", "shell_tool", "unified_exec", "view_image", "multi_agent", "image_generation",
       "sleep_tool", "skill_search", "tool_suggest", "browser_use", "computer_use", "in_app_browser"]
QUIET = [x for name in OFF for x in ("--disable", name)] + ["-c", "mcp_servers={}"]


def command() -> str:
    """The Codex command line: on the PATH, or inside the desktop app, which ships one without putting it there."""
    for c in [os.getenv("JEV_CODEX_BIN") or "", *PLACES]:
        found = shutil.which(os.path.expanduser(c)) if c else None
        if found:
            return found
    raise ValueError("the Codex command line was not found: install Codex, or set JEV_CODEX_BIN to its path")


class CodexResponder:
    def __init__(self, model: str | None = None, command_: str | None = None, effort: str | None = None, warm: bool = False, **_):
        self.model = model or os.getenv("JEV_FAST_MODEL", "")
        if not self.model:
            raise ValueError("set JEV_FAST_MODEL: the fast Codex model that does the talking (one from its own list, /model)")
        self.command = command_ or command()
        self.effort = effort or os.getenv("JEV_FAST_EFFORT") or "low"
        self.proc: asyncio.subprocess.Process | None = None
        self.thread, self.system = "", ""
        self.seq = 0
        self.owed = 0                             # turns started whose end has not been read yet
        self.lock = asyncio.Lock()
        self.warming: asyncio.Task | None = None
        if warm:                                  # for whoever makes it before the call: the first reply of a process is slow
            try:
                self.warming = asyncio.get_running_loop().create_task(self.warm())
            except RuntimeError:                  # made outside a loop: the first reply pays for it
                pass

    # ---- the process and its protocol
    async def _send(self, method: str, params: dict | None = None, reply: bool = True) -> int:
        msg: dict = {"method": method, "params": params or {}}
        if reply:
            self.seq += 1
            msg["id"] = self.seq
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()
        return self.seq

    async def _read(self) -> dict:
        line = await self.proc.stdout.readline()
        if not line:
            raise RuntimeError("Codex stopped while talking (is it signed in? run `codex login`)")
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return {}
        if "id" in e and "method" in e:           # it asks us something (an approval): nothing is granted here
            self.proc.stdin.write((json.dumps({"id": e["id"], "error": {"code": -32601, "message": "not available"}}) + "\n").encode())
        return e

    async def _answer(self, rid: int) -> dict:
        while True:
            e = await self._read()
            if e.get("id") == rid and "method" not in e:
                if "error" in e:
                    raise RuntimeError(str((e["error"] or {}).get("message") or "Codex refused the request")[:200])
                return e.get("result") or {}

    async def _start(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CODEX_")}     # not a child of another session
        self.proc = await asyncio.create_subprocess_exec(self.command, "app-server", *QUIET, stdin=asyncio.subprocess.PIPE,
                                                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                         env=env, limit=1 << 22)
        self.thread, self.owed = "", 0
        await self._answer(await self._send("initialize", {"clientInfo": {"name": "jev-interaction", "title": "Jev-Interaction", "version": "0"}}))
        await self._send("initialized", reply=False)

    async def _thread(self, system: str) -> str:
        got = await self._answer(await self._send("thread/start", {
            "model": self.model, "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
            "baseInstructions": system + SPOKEN, "config": {"model_reasoning_effort": self.effort}}))
        return (got.get("thread") or {}).get("id") or ""

    async def _turn(self, thread: str, text: str):
        """One turn: its text as it is written, piece by piece. Ends when the turn does; raises when it failed."""
        await self._answer(await self._send("turn/start", {"threadId": thread, "input": [{"type": "text", "text": text}]}))
        self.owed += 1
        streamed = False
        while True:
            e = await self._read()
            kind, given = e.get("method"), e.get("params") or {}
            if given.get("threadId") not in (None, thread):
                continue
            if kind == "item/agentMessage/delta":
                streamed = True
                yield given.get("delta") or ""
            elif kind == "item/completed" and not streamed and (given.get("item") or {}).get("type") == "agentMessage":
                yield (given["item"].get("text") or "") + "\n"       # no deltas from this version: the whole of it
            elif kind == "turn/completed":
                self.owed -= 1
                turn = given.get("turn") or {}
                if turn.get("status") == "failed":
                    raise RuntimeError(str((turn.get("error") or {}).get("message") or "Codex could not answer")[:200])
                return

    async def _settle(self) -> None:
        while self.owed:                          # a turn nobody finished listening to: stopped, and read to its end
            await self._send("turn/interrupt", {"threadId": self.thread}, reply=False)
            while self.owed:
                e = await self._read()
                if e.get("method") == "turn/completed":
                    self.owed -= 1

    async def warm(self) -> None:
        async with self.lock:
            try:
                if self.proc is None or self.proc.returncode is not None:
                    await self._start()
                async for _ in self._turn(await self._thread("Reply with one word."), "ok"):
                    pass
            except Exception:  # noqa: BLE001 - only a head start: the first real reply says what is wrong, if anything
                pass

    async def aclose(self) -> None:
        if self.warming is not None:
            self.warming.cancel()
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None

    async def lines(self, messages: list[dict], max_tokens: int = 160):
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self._start()
            await self._settle()
            fresh = not self.thread or system != self.system
            if fresh:
                self.thread, self.system = await self._thread(system), system
            buf = ""
            async for piece in self._turn(self.thread, ClaudeCodeResponder.unheard(messages, fresh)):
                buf += piece
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        yield line.strip()
            if buf.strip():
                yield buf.strip()
