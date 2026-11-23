"""Claude Code's own model as the responder: the harness the user already has, on the account they are already signed
in to, with no key of ours.

One `claude -p` process is kept open for the call, speaking stream-json both ways. Starting the command line takes a
second or two, so it is paid once; after that a reply is one message in and its text streamed back. The process keeps
the conversation itself, so each reply sends only what it has not heard yet: everything after the agent's last line.

It runs with no tools, no MCP servers, no settings and no session file: it only talks. The model is the one the user
chose for talking (JEV_FAST_MODEL: a fast one, "haiku" for instance); the session they work in keeps its own.

Not checked against a signed-in command line yet: written from the documented stream-json format.
"""
from __future__ import annotations

import asyncio
import json
import os


# The command line is a coding agent's: its model does not know, unless told, that here nothing it writes is read. Seen
# on a real call (11-23): a line of its own planning, in English, went out to the voice.
SPOKEN = ("\n\nEverything you write here is said aloud to the user by a voice, word for word as you write it (a line that "
          "starts with a slash is the one exception). So you write only what you say to them.")


class ClaudeCodeResponder:
    def __init__(self, model: str | None = None, command: str | None = None, **_):
        self.model = model or os.getenv("JEV_FAST_MODEL", "")
        if not self.model:
            raise ValueError("set JEV_FAST_MODEL: the fast Claude Code model that does the talking (for example haiku)")
        self.command = command or os.getenv("JEV_CLAUDE_BIN") or "claude"
        self.proc: asyncio.subprocess.Process | None = None
        self.system = ""
        self.owed = 0                             # replies asked for whose end has not been read yet
        self.lock = asyncio.Lock()

    def argv(self, system: str) -> list[str]:
        return [self.command, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--model", self.model, "--system-prompt", system + SPOKEN, "--tools", "",
                "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence"]

    async def _start(self, system: str) -> None:
        await self.aclose()
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}   # not a child of another session
        self.proc = await asyncio.create_subprocess_exec(*self.argv(system), stdin=asyncio.subprocess.PIPE,
                                                         stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                         env=env, limit=1 << 22)
        self.system, self.owed = system, 0

    async def aclose(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None

    @staticmethod
    def unheard(messages: list[dict], fresh: bool) -> str:
        """What goes to the process now. One that has been on the call hears only what came after the agent's last
        line; one just started (the first reply, or a persona put on the line) hears the call so far, told plainly."""
        turns = [m for m in messages if m.get("role") != "system"]
        last = max((i for i, m in enumerate(turns) if m["role"] == "assistant"), default=-1)
        tail = "\n".join(m["content"] for m in turns[last + 1:])
        if not fresh or last < 0:
            return tail
        said = "\n".join(("You: " if m["role"] == "assistant" else "") + m["content"] for m in turns[:last + 1])
        return f"(The call so far, before you came on:\n{said})\n{tail}"

    async def _read(self) -> dict | None:
        line = await self.proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {}

    async def lines(self, messages: list[dict], max_tokens: int = 160):
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        async with self.lock:
            fresh = self.proc is None or self.proc.returncode is not None or system != self.system
            if fresh:
                await self._start(system)
            while self.owed:                      # a reply nobody finished listening to: read to its end first
                e = await self._read()
                if e is None:
                    raise RuntimeError("Claude Code stopped while talking")
                self.owed -= e.get("type") == "result"
            text = self.unheard(messages, fresh)
            self.proc.stdin.write((json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}},
                                              ensure_ascii=False) + "\n").encode())
            await self.proc.stdin.drain()
            self.owed += 1
            buf, streamed = "", False
            while True:
                e = await self._read()
                if e is None:
                    raise RuntimeError("Claude Code stopped while talking (is it signed in? run `claude` and /login)")
                kind = e.get("type")
                if kind == "stream_event":
                    delta = (e.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta":
                        buf, streamed = buf + delta.get("text", ""), True
                elif kind == "assistant" and not streamed:     # no partial messages from this version: the whole of it
                    buf += "".join(b.get("text", "") for b in (e.get("message") or {}).get("content") or [] if b.get("type") == "text")
                elif kind == "result":
                    self.owed -= 1
                    if e.get("is_error"):
                        raise RuntimeError(str(e.get("result") or "Claude Code could not answer")[:200])
                    break
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        yield line.strip()
            if buf.strip():
                yield buf.strip()
