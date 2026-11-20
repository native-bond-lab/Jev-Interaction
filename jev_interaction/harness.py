"""A coding agent in another window as an executor: Claude Code, Codex, DeepSeek Harness.

One hub on this machine. On one side the voice (the Sessions on a call); on the other the connectors, one per harness
session: a thin piece that lives with the harness, pushes the user's words in and reports what happens. Every harness
speaks the same small protocol to the hub, as JSON objects with a `type`:

    connector -> hub    hello {harness, cwd, steer,     it is there (`steer`: "now" when more words reach the turn that
                               acks}                    is running, "turn" when they wait for it to end; `acks`: a
                                                        pushed prompt is followed by a turn_start, so one that is not
                                                        was not taken)
                        turn_start {text, ours}         a turn began; `ours`: it is one the hub pushed
                        progress {text}                 what it is doing now, in a few words
                        tool_done {}                    a tool call went through or was refused: a "may I" is over
                        say {task, text}                the agent's own words for the user, written to be spoken
                        ask {id, text}                  it waits for the user's permission
                        turn_end {text, error}          the turn ended; its last message, or why it broke off
    hub -> connector    prompt {task, text}             the user's words, as a new turn
                        steer {task, text}              more words for a task that is going
                        cancel {task}                   stop it, where the harness can
                        answer {id, behavior}           "allow" | "deny"

`HarnessExecutor` is the executor the voice is given (tasks.py). A task started by voice is pushed to the harness and
comes back when its turn ends, with the words the agent wrote to be spoken (`say`) or, failing that, its last message.
A turn the user typed in the harness themself is taken up as a task too once it has run a while
(`Hub.adopt_after_s`), so the voice can tell them when it is done; a short one is left alone.

A "may I" from the harness is put to the user through the voice (`Tell.ask`). The answer goes back to the harness only
with `voice_approvals` on; off (the default), the user is told and answers it on their own screen.
"""
from __future__ import annotations

import asyncio
import pathlib
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .tasks import Task, Tell

HUB_FILE = pathlib.Path.home() / ".jev-interaction" / "hub"     # where the call server with the hub says it is: one line,
DEFAULT_HUB = "ws://127.0.0.1:8080/harness/ws"                  # its ws:// address, read by the connectors on this machine


def announce(port: int) -> None:
    """The call server with the hub is on this port: written where connectors look (they start on their own, from
    inside a harness, and are told nothing)."""
    try:
        HUB_FILE.parent.mkdir(parents=True, exist_ok=True)
        HUB_FILE.write_text(f"ws://127.0.0.1:{port}/harness/ws\n", encoding="utf-8")
    except OSError:
        pass                                    # connectors fall back to the default port


def where() -> str:
    """The hub's address for a connector: JEV_INTERACTION_HUB, or what the call server wrote, or the default port."""
    import os
    try:
        return os.getenv("JEV_INTERACTION_HUB") or HUB_FILE.read_text(encoding="utf-8").strip() or DEFAULT_HUB
    except OSError:
        return DEFAULT_HUB


@dataclass
class Job:
    """A task of the voice's on a harness session."""
    task: Task
    tell: Tell
    done: asyncio.Future
    owed: int = 1                # turns of the harness still to end before it has come back
    skip: int = 0                # turn ends that are not its own (a turn was already running when it was pushed)
    said: str = ""               # what the agent wrote for the user to hear
    taken: asyncio.Event = field(default_factory=asyncio.Event)   # the harness showed a sign of life after the push


@dataclass
class Link:
    """One harness session that a connector has put on the hub."""
    harness: str
    send: Callable[[dict], Awaitable[None]]
    cwd: str = ""
    steer: str = "turn"
    acks: bool = False           # a pushed prompt is followed by a turn_start (the connector says so in its hello)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    busy: bool = False           # a turn is running
    reports: bool = False        # it tells the hub when turns end (a connector with events; without, `say` ends a task)
    jobs: list[Job] = field(default_factory=list)
    turn: object | None = None   # the turn going on that nobody asked for by voice, until it is taken up or ends
    asks: dict[str, asyncio.Task] = field(default_factory=dict)   # the "may I" out to the user, by its id
    seen: float = field(default_factory=time.monotonic)
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None


def verdict(text: str) -> str | None:
    """The user's answer to a "may I", as the responder passed it on: "allow", "deny", or None when it says neither."""
    t = (text or "").lower()
    if "deny" in t:
        return "deny"
    return "allow" if "allow" in t else None


def _short(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


class Hub:
    TAKEN_S = 8.0                # an idle harness that acks takes pushed words within this, or it did not take them

    def __init__(self, *, kind: str = "agent", adopt_after_s: float = 30.0, voice_approvals: bool = False):
        self.kind = kind                          # the executor's name on the voice side
        self.adopt_after_s = adopt_after_s        # a turn the user typed is taken up as a task once it has run this long
        self.voice_approvals = voice_approvals    # the user's spoken "allow" / "deny" is passed back to the harness
        self.links: dict[str, Link] = {}
        self.voices: list = []                    # the Sessions on a call, the latest last
        self.pushed: deque[str] = deque(maxlen=20)

    # ------------------------------------------------------------------ the two sides
    def attach(self, session) -> None:
        self.voices.append(session)

    def detach(self, session) -> None:
        if session in self.voices:
            self.voices.remove(session)

    def voice(self):
        return next((s for s in reversed(self.voices) if not s.closed), None)

    def executor(self) -> HarnessExecutor:
        return HarnessExecutor(self)

    def add(self, link: Link) -> Link:
        self.links[link.id] = link
        link.worker = asyncio.get_running_loop().create_task(self._work(link))
        return link

    def drop(self, link: Link) -> None:
        """The connector went away: its window closed. What was running on it has failed."""
        self.links.pop(link.id, None)
        if link.worker is not None:
            link.worker.cancel()
        for ask in link.asks.values():
            ask.cancel()
        for job in list(link.jobs):
            if not job.done.done():
                job.done.set_exception(RuntimeError(f"{link.harness} went away before it finished"))

    def pick(self, link_id: str | None = None) -> Link | None:
        if link_id:
            return self.links.get(link_id)
        return max(self.links.values(), key=lambda k: k.seen, default=None)

    def post(self, link: Link, event: dict) -> None:
        """An event from the connector, handled in the order it came without making the sender wait."""
        link.seen = time.monotonic()
        link.inbox.put_nowait(event)

    async def _work(self, link: Link) -> None:
        while True:
            event = await link.inbox.get()
            try:
                await self.event(link, event)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad event must not stop the ones after it
                pass

    # ------------------------------------------------------------------ what the harness reports
    async def event(self, link: Link, e: dict) -> None:
        kind = e.get("type")
        for job in link.jobs:
            job.taken.set()                       # anything at all from the harness: it is there and working
        if kind == "hello":
            link.cwd, link.steer = e.get("cwd") or link.cwd, e.get("steer") or link.steer
            link.acks = bool(e.get("acks", link.acks))
        elif kind == "turn_start":
            await self._turn_start(link, e.get("text") or "", bool(e.get("ours")))
        elif kind == "turn_end":
            self._turn_end(link, e.get("text") or "", e.get("error") or "")
        elif kind == "progress":
            link.busy = True
            if link.jobs and e.get("text"):
                await link.jobs[0].tell.progress(e["text"])
        elif kind == "tool_done":
            self._asks_over(link)
        elif kind == "say":
            await self._say(link, str(e.get("task") or ""), e.get("text") or "")
        elif kind == "ask":
            await self._ask(link, str(e.get("id") or ""), e.get("text") or "")

    async def _turn_start(self, link: Link, text: str, ours: bool) -> None:
        link.busy = link.reports = True
        if ours or any(p and p in text for p in self.pushed) or link.jobs:
            return                                # the voice asked for it: it has its task already
        link.turn = token = object()              # the user typed it there: taken up if it is still going later
        asyncio.get_running_loop().create_task(self._adopt_later(link, token, text))

    async def _adopt_later(self, link: Link, token: object, text: str) -> None:
        await asyncio.sleep(self.adopt_after_s)
        if link.turn is token and link.id in self.links:
            await self._adopt(link, text)

    async def _adopt(self, link: Link, text: str) -> None:
        """A turn the user started in the harness becomes a task of the voice's, so it can say when it is done."""
        link.turn = None
        voice = self.voice()
        if voice is None or self.kind not in voice.executors:
            return
        about = f'what they typed to {link.harness} themself: "{_short(text)}"' if text else f"what {link.harness} is working on"
        await voice.start_task(self.kind, about, observed=True, link=link.id)
        for _ in range(5):                        # its executor takes its place on the link before anything else comes
            if link.jobs:
                break
            await asyncio.sleep(0)

    def _turn_end(self, link: Link, text: str, error: str = "") -> None:
        link.busy, link.reports, link.turn = False, True, None
        self._asks_over(link)
        for i, job in enumerate(list(link.jobs)):
            if i == 0 and job.skip > 0:
                job.skip -= 1                     # the turn that was running before it was pushed
            elif i == 0 and error and not job.done.done():
                job.done.set_exception(RuntimeError(f"{link.harness} could not go on: {_short(error, 200)}"))
            elif i == 0 or job.said:              # its own turn; or one answered together with it (`say` named it)
                job.owed -= 1
                if job.owed <= 0 and not job.done.done():
                    job.done.set_result(job.said or text)

    async def _say(self, link: Link, task_id: str, text: str) -> None:
        job = next((j for j in link.jobs if str(j.task.id) == task_id), None) or (link.jobs[0] if link.jobs else None)
        if job is not None:
            job.said = text
            if not link.reports and not job.done.done():     # nobody will say when the turn ends: this is the end
                job.done.set_result(text)
            return
        voice = self.voice()                      # words for the user with no task behind them: told as news
        if voice is not None and self.kind in voice.executors and text:
            await voice.start_task(self.kind, f"a message from {link.harness}", said=text, link=link.id)

    async def _ask(self, link: Link, ask_id: str, text: str) -> None:
        if not link.jobs:                         # a turn nobody asked for by voice needs them: taken up now
            await self._adopt(link, "")
            if not link.jobs:
                return
        self._asks_over(link)                     # one question at a time: a new one replaces the one before it
        link.asks[ask_id] = asyncio.get_running_loop().create_task(self._asking(link, link.jobs[0], ask_id, text))

    async def _asking(self, link: Link, job: Job, ask_id: str, text: str) -> None:
        how = 'Pass their answer on as "allow" or "deny".' if self.voice_approvals else "They answer it on their own screen."
        try:
            answer = await job.tell.ask(f"{_short(text, 300)} {how}")
        finally:
            if link.asks.get(ask_id) is asyncio.current_task():
                del link.asks[ask_id]
        behavior = verdict(answer) if self.voice_approvals else None
        if behavior:
            await link.send({"type": "answer", "id": ask_id, "behavior": behavior})

    def _asks_over(self, link: Link) -> None:
        for ask in list(link.asks.values()):
            ask.cancel()
        link.asks.clear()


class HarnessExecutor:
    describe = ("work for the coding agent open on the user's computer: reading, changing and running code, anything in "
                "their project. Say what to do in full; it has not heard the call")

    def __init__(self, hub: Hub):
        self.hub = hub

    def _job(self, task: Task) -> tuple[Link, Job] | tuple[None, None]:
        for link in self.hub.links.values():
            for job in link.jobs:
                if job.task is task:
                    return link, job
        return None, None

    async def run(self, task: Task, tell: Tell) -> str:
        given = task.given
        if "said" in given:                       # words the harness had for the user, with no work behind them
            return given["said"]
        link = self.hub.pick(given.get("link"))
        if link is None:
            raise RuntimeError("no coding agent is connected on this computer")
        job = Job(task, tell, asyncio.get_running_loop().create_future())
        waits = False
        if not given.get("observed"):
            job.skip = 1 if link.busy and not link.jobs else 0
            waits = link.acks and not link.busy and not link.jobs     # idle: the words should be taken at once
            link.turn = None                      # a turn already running is not taken up apart from this one
            self.hub.pushed.append(task.about)
            await link.send({"type": "prompt", "task": str(task.id), "text": task.about})
        link.jobs.append(job)
        try:
            if waits:
                try:
                    await asyncio.wait_for(job.taken.wait(), self.hub.TAKEN_S)
                except asyncio.TimeoutError:
                    raise RuntimeError(f"{link.harness} did not take the words; it may not be listening to the voice "
                                       "(it has to be started with its voice channel on)") from None
            return await job.done
        except asyncio.CancelledError:
            if not given.get("observed") and link.id in self.hub.links:
                try:
                    await link.send({"type": "cancel", "task": str(task.id)})
                except Exception:  # noqa: BLE001 - best effort: the window may be gone
                    pass
            raise
        finally:
            if job in link.jobs:
                link.jobs.remove(job)
            if not link.jobs:
                self.hub._asks_over(link)

    async def steer(self, task: Task, text: str) -> None:
        link, job = self._job(task)
        if link is None:
            return
        if link.steer == "turn":                  # the words wait for the turn to end and are a turn of their own
            job.owed += 1
        self.hub.pushed.append(text)
        await link.send({"type": "steer", "task": str(task.id), "text": text})
