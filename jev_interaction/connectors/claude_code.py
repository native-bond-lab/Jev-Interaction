"""Claude Code's side of voice interaction: the server of the `interaction` plugin (connectors/claude-code/).

Claude Code starts this process with the session, as an MCP server on stdio. Nothing happens until the user runs
/interaction:start; then the session itself keeps the loop going, with three tools:

    listen    waits for what the user asks for out loud and returns it. The first call brings the voice up: it finds
              the call server on this machine or starts one (a free port, the hub on, the pet shown), and joins its hub
    say       words for the user to hear: the outcome of a task, in a sentence or two
    stop      ends voice interaction

So the session works as it always does, on its own model; the talking is done by the call server, on the fast model the
user chose (JEV_FAST_MODEL, Claude Code's own: adapters/claude_cli.py). No channel and no launch flag are involved.

Claude Code's hooks report what the session is doing by calling a fourth tool, `hook`, which the model is never shown
(hooks of type mcp_tool): a prompt typed, a tool about to run, a permission asked, the turn ended. While voice
interaction is on, the Stop hook is answered with "call listen": the loop does not end because a turn did.

The hub's small protocol is in harness.py. What Claude Code cannot do from outside: a turn that is running cannot be
interrupted, so more words for a task are heard when it next listens.

MCP is spoken by hand here (newline-delimited JSON-RPC): a handful of messages, nothing to install beside this package.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import threading

from ..harness import where

HARNESS = "Claude Code"
SERVER = "jev"
LISTEN_S = 45 * 60               # a listen call ends after this with "nobody asked"; under the server's tool time limit
HOME = pathlib.Path.home() / ".jev-interaction"

INSTRUCTIONS = (
    "Voice interaction (the /interaction:start command): the user talks to a voice companion, which hands what they ask "
    "for to you through the `listen` tool. Take each as you would a typed prompt of theirs. They are listening, not "
    "reading: when a task is done, call `say` with its number and what to tell them, a sentence or two in plain spoken "
    "words, what matters and nothing else, no code, no paths, no lists; the details stay on the screen. Then call "
    "`listen` again.")

LISTEN = {"name": "listen", "description": "Wait for what the user asks for out loud and return it. Call it to start voice "
          "interaction, and again after each task, until the user ends it.", "inputSchema": {"type": "object", "properties": {}}}
SAY = {"name": "say", "description": "Say something to the user out loud: the outcome of what they asked for by voice, or "
       "something they need to know now. A sentence or two of plain spoken words.",
       "inputSchema": {"type": "object", "required": ["text"], "properties": {
           "text": {"type": "string", "description": "what to say, as it should be heard"},
           "task": {"type": "string", "description": "the number of the task this answers, as listen gave it"}}}}
STOP = {"name": "stop", "description": "End voice interaction (the user asked to, or typed that they are done with it).",
        "inputSchema": {"type": "object", "properties": {}}}
KEEP_ON = json.dumps({"decision": "block", "reason": "Voice interaction is on. Call the listen tool to wait for what the "
                      "user says next; call stop instead if they asked to end it."})


# ---------------------------------------------------------------------- hooks -> the hub's events
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


OWN = re.compile(r"__(listen|say|stop|hook)$")       # this server's own tools: not work worth telling about


def events(hook: dict) -> list[dict]:
    """One hook payload from Claude Code as the hub's events (harness.py)."""
    name, tool = hook.get("hook_event_name"), str(hook.get("tool_name") or "")
    if name == "UserPromptSubmit":
        return [{"type": "turn_start", "text": str(hook.get("prompt") or ""), "ours": False}]
    if name == "PreToolUse":                      # a new tool call: whatever was asked about the one before is settled
        return [] if OWN.search(tool) else [{"type": "tool_done"}, {"type": "progress", "text": _doing(tool, hook.get("tool_input") or {})}]
    if name == "PermissionRequest":
        what = _doing(tool, hook.get("tool_input") or {})
        return [] if OWN.search(tool) else [{"type": "ask", "id": "permission", "text": f"{HARNESS} asks to use {tool or 'a tool'} ({what})"}]
    if name in ("PostToolUse", "PostToolUseFailure", "PermissionDenied"):
        return [] if OWN.search(tool) else [{"type": "tool_done"}]
    if name == "Stop":
        return [{"type": "turn_end", "text": str(hook.get("last_assistant_message") or "")}]
    if name == "StopFailure":                     # the turn broke off on an error of the model's service, not on the work
        why = str(hook.get("last_assistant_message") or hook.get("error_details") or hook.get("error") or "an error")
        return [{"type": "turn_end", "text": "", "error": why}]
    return []


def hook_of(args: dict) -> dict:
    """The arguments of a `hook` tool call (hooks.json fills them from the hook's own input, "${tool_name}" and so on)
    as the hook payload `events` reads. A field the hook did not have comes through unfilled and counts as empty."""
    got = {k: ("" if isinstance(v, str) and v.startswith("${") else v) for k, v in args.items()}
    tool_input = {k: got[k] for k in ("description", "command", "file_path", "pattern") if got.get(k)}
    return {"hook_event_name": got.get("event"), "prompt": got.get("prompt"), "tool_name": got.get("tool_name"),
            "tool_input": tool_input, "last_assistant_message": got.get("last_assistant_message"), "error": got.get("error")}


# ---------------------------------------------------------------------- the call server, found or started
def _health(url: str) -> dict | None:
    """The call server behind a hub address, asked how it is; None when nothing answers. Never through a proxy: it is
    on this machine, and a system proxy that does not except 127.0.0.1 would take the request and lose it."""
    import urllib.request
    origin = url.replace("ws://", "http://").split("/harness/")[0]
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(origin + "/api/health", timeout=2) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    """The call server this connector started, and the pet it showed; both end with the connector."""

    def __init__(self):
        self.server: subprocess.Popen | None = None
        self.pet: subprocess.Popen | None = None

    def start(self) -> tuple[str, str]:
        """(hub address, "") once a call server is up and set up; ("", why not) otherwise. Blocking: run in a thread."""
        url = where()
        health = _health(url)
        if health is None:
            try:
                import fastapi  # noqa: F401  (the call server's extras)
                import uvicorn  # noqa: F401
            except ImportError:
                return "", 'the call server is not installed: pip install "jev-interaction[server]"'
            port = _free_port()
            HOME.mkdir(parents=True, exist_ok=True)
            # the talking is done by Claude Code's own model unless the user chose another on the setup page
            env = {**os.environ, "JEV_HARNESS": "1", "JEV_HOME": os.getenv("JEV_HOME") or str(HOME), "JEV_LLM_DEFAULT": "claude-code"}
            log = open(HOME / "server.log", "ab")        # noqa: SIM115 - the server's for as long as it runs
            self.server = subprocess.Popen([sys.executable, "-m", "jev_interaction.cli", "serve", "--port", str(port), "--quiet"],
                                           env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
            url = f"ws://127.0.0.1:{port}/harness/ws"
            for _ in range(180):                  # a first start loads models: up to a minute and a half
                health = _health(url)
                if health is not None or self.server.poll() is not None:
                    break
                threading.Event().wait(0.5)
            if health is None:
                self.stop()
                return "", f"the call server did not start (see {HOME / 'server.log'})"
        if health.get("harness") is None:
            return "", "a call server is running on this machine without its hub for coding agents (JEV_HARNESS=1)"
        if health.get("missing"):                 # the first time: the user chooses the models on the setup page
            page = url.replace("ws://", "http://").split("/harness/")[0] + "/"
            self.open(page)
            return "", ("voice interaction is not set up yet (" + ", ".join(health["missing"]) + "). The setup page is open in "
                        f"the browser ({page}): there the user chooses the fast model that does the talking and the "
                        "speech models, and then runs /interaction:start again")
        if self.server is not None and self.pet is None:
            self.show(url.replace("ws://", "http://").split("/harness/")[0] + "/pet")
        return url, ""

    @staticmethod
    def open(page: str) -> None:
        if (os.getenv("JEV_PET") or "").lower() not in ("off", "0", "no"):      # off: nobody is to see it (a test)
            import webbrowser
            webbrowser.open(page)

    def show(self, page: str) -> None:
        """The pet: the small window of its own when there is one (JEV_PET_APP: the pet/ folder, with Electron
        installed), the browser otherwise."""
        if (os.getenv("JEV_PET") or "").lower() in ("off", "0", "no"):
            return
        app = pathlib.Path(os.getenv("JEV_PET_APP") or "")
        electron = app / "node_modules" / ".bin" / "electron"
        if os.getenv("JEV_PET_APP") and electron.exists():
            self.pet = subprocess.Popen([str(electron), str(app)], env={**os.environ, "JEV_PET_URL": page}, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            self.open(page)

    def stop(self) -> None:
        for p in (self.pet, self.server):
            if p is not None and p.poll() is None:
                try:
                    os.killpg(p.pid, 15)
                except OSError:
                    p.terminate()
        self.pet = self.server = None


# ---------------------------------------------------------------------- the MCP server
class Connector:
    def __init__(self, cwd: str, out=None, url: str | None = None, service: Service | None = None):
        self.cwd, self.out = cwd, out or sys.stdout
        self.url = url                            # a hub given by hand (a test): joined as it is, nothing started
        self.service = service or Service()
        self.hub = None                           # the socket to the call server's hub, while joined
        self.reader: asyncio.Task | None = None
        self.on = False                           # voice interaction is on in this session
        self.prompts: asyncio.Queue = asyncio.Queue()
        self.turn: str | None = None              # the turn the session is in, until it ends: "voice" (a task that
                                                  # listen handed it) or "typed" (the user typed a prompt)
        self.calls: dict = {}                     # tool calls in progress, by their request id
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
        except Exception:  # noqa: BLE001 - the call server went away
            self.hub = None
            return False

    # ---- the hub
    async def join(self) -> str:
        """On the hub, or why not (a sentence for the session to tell the user)."""
        if self.hub is not None:
            return ""
        url, why = (self.url, "") if self.url else await asyncio.to_thread(self.service.start)
        if why:
            return why
        import websockets
        try:
            try:
                self.hub = await websockets.connect(url, max_size=None, proxy=None)     # this machine: never a proxy
            except TypeError:                     # websockets before 15: no proxy support, no such argument
                self.hub = await websockets.connect(url, max_size=None)
        except Exception as exc:  # noqa: BLE001
            return f"the call server could not be reached: {type(exc).__name__}"
        await self.to_hub({"type": "hello", "harness": HARNESS, "cwd": self.cwd, "steer": "turn", "acks": True})
        self.reader = asyncio.get_running_loop().create_task(self._from_hub(self.hub))
        return ""

    async def _from_hub(self, ws) -> None:
        try:
            async for raw in ws:
                e = json.loads(raw)
                if e.get("type") in ("prompt", "steer") and e.get("text"):
                    self.prompts.put_nowait(e)    # "cancel", "answer": a running turn takes neither from outside
        except Exception:  # noqa: BLE001 - the call server went away: the next listen finds or starts one
            pass
        finally:
            if self.hub is ws:
                self.hub = None

    async def leave(self) -> None:
        self.on, self.turn = False, None
        ws, self.hub = self.hub, None
        if ws is not None:
            await ws.close()

    # ---- the tools
    async def listen(self) -> str:
        why = await self.join()
        if why:
            self.on = False
            return f"Voice interaction did not start: {why}. Tell the user that, in a sentence."
        self.on = True
        if self.turn == "voice":                  # back from the work: that task's turn is over
            self.turn = None
            await self.to_hub({"type": "turn_end", "text": ""})
        try:
            e = await asyncio.wait_for(self.prompts.get(), LISTEN_S)
        except asyncio.TimeoutError:
            return "Nobody has asked for anything. Call listen again to keep listening."
        task, self.turn = str(e.get("task") or ""), "voice"
        await self.to_hub({"type": "turn_start", "text": e["text"], "ours": True})
        return (f"The user asks, out loud (task {task}):\n{e['text']}\n\nDo it as you would a typed request. When it is done, "
                f'call say with task "{task}" and what to tell them, a sentence or two of plain spoken words; then call listen again.')

    async def hook(self, args: dict) -> str:
        """One of Claude Code's hooks: passed on to the hub; answered with no verdict, except that a turn ending while
        voice interaction is on is sent back to listening."""
        hook = hook_of(args)
        for event in events(hook):
            if event["type"] == "turn_start":
                self.turn = self.turn or "typed"
            elif event["type"] == "turn_end":
                if self.turn is None:             # no turn is open: a task's turn ended when the session went back to
                    continue                      # listen, and this is only the session stopping after it
                self.turn = None
            await self.to_hub(event)
        return KEEP_ON if hook["hook_event_name"] == "Stop" and self.on else "{}"

    async def call(self, mid, name: str, args: dict) -> None:
        try:
            if name == "hook":
                text = await self.hook(args)
            elif name == "listen":
                text = await self.listen()
            elif name == "say":
                sent = await self.to_hub({"type": "say", "task": str(args.get("task") or ""), "text": str(args.get("text") or "")})
                text = "Said." if sent else "Voice interaction is not on: nothing was said."
            elif name == "stop":
                await self.leave()
                text = "Voice interaction is off."
            else:
                self.write({"id": mid, "error": {"code": -32602, "message": f"no such tool: {name}"}})
                return
            self.write({"id": mid, "result": {"content": [{"type": "text", "text": text}]}})
        except asyncio.CancelledError:            # the user interrupted it (Esc): they are back at the keyboard
            self.on = False
            raise
        finally:
            self.calls.pop(mid, None)

    # ---- Claude Code -> us
    async def on_mcp(self, m: dict) -> None:
        method, mid, params = m.get("method"), m.get("id"), m.get("params") or {}
        if method == "initialize":
            self.write({"id": mid, "result": {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                                              "capabilities": {"tools": {}}, "serverInfo": {"name": SERVER, "version": "0.2.0"},
                                              "instructions": INSTRUCTIONS}})
        elif method == "ping":
            self.write({"id": mid, "result": {}})
        elif method == "tools/list":
            self.write({"id": mid, "result": {"tools": [LISTEN, SAY, STOP]}})
        elif method == "tools/call":              # each in its own task: a hook must get through while listen waits
            self.calls[mid] = asyncio.get_running_loop().create_task(self.call(mid, str(params.get("name")), params.get("arguments") or {}))
        elif method == "notifications/cancelled":
            call = self.calls.get(params.get("requestId"))
            if call is not None:
                call.cancel()
        elif mid is not None and method:          # a request this server has no answer to
            self.write({"id": mid, "error": {"code": -32601, "message": f"no such method: {method}"}})

    async def run(self, stdin=None) -> None:
        loop, lines = asyncio.get_running_loop(), asyncio.Queue()
        stdin = stdin or sys.stdin

        def read():                               # stdin on a thread: a pipe from Claude Code, closed when the session ends
            for line in stdin:
                loop.call_soon_threadsafe(lines.put_nowait, line)
            loop.call_soon_threadsafe(lines.put_nowait, None)
        threading.Thread(target=read, daemon=True).start()
        try:
            while (line := await lines.get()) is not None:
                if line.strip():
                    try:
                        await self.on_mcp(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        finally:
            for call in list(self.calls.values()):
                call.cancel()
            await self.leave()
            self.service.stop()                   # what this session started ends with it


def main(url: str | None = None, cwd: str | None = None) -> int:
    asyncio.run(Connector(cwd or os.getenv("CLAUDE_PROJECT_DIR") or os.getcwd(), url=url).run())
    return 0
