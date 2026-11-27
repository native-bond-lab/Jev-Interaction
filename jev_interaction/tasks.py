"""Work the agent sets going in the background while the call carries on.

The agent on the line is the voice: it listens, talks and picks its moments. Anything that takes longer than a breath
is handed to an executor (a memory service, a model that thinks longer, a search, a coding agent in another window) as
a task. The call does not wait for it:

    the task is on the call's record     started, come back, failed, waiting on the user: each is an entry of the ledger
                                         where it happened, read by the responder and by Jev like every other line
    what is still going is always shown  the bracketed line of every reply lists the tasks that are running and the ones
                                         with news not told yet, so the agent never states an outcome it does not have
    the result is told at a moment       not when it lands: in a quiet, or with the answer to what the user is saying

An executor is anything with `run(task, tell) -> str`: it returns what came back ("" for nothing) or raises; `tell`
reports how far it has got and asks the user what only they can answer. Being cancelled is how it is stopped. One that
can take more words while it runs has `steer(task, text)` as well.

The responder starts and steers tasks with lines of their own that start with a slash (`action`); such a line is acted
on, kept in the record as the agent's own, and never spoken.
"""
from __future__ import annotations

import asyncio
import pathlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .session import Session

RUNNING, WAITING, DONE, EMPTY, FAILED, STOPPED = "running", "waiting", "done", "empty", "failed", "stopped"
OPEN = (RUNNING, WAITING)            # not finished: the call has something to wait for

PROMPT = (pathlib.Path(__file__).parent / "prompts" / "tasks.md").read_text(encoding="utf-8")


@dataclass
class Task:
    id: int              # 1, 2, ... within the call: what the responder calls it
    kind: str            # the executor's name: "memory", "think", "search", "agent", ...
    about: str           # what to do, in the words it was given
    started: float       # seconds into the call
    status: str = RUNNING
    ended: float | None = None
    progress: str = ""   # the last thing it reported
    question: str = ""   # what it is waiting on the user for
    result: str = ""     # what came back, or why it failed
    news: bool = False   # it came back or asked something, and no line of the agent's has carried that yet
    given: dict = field(default_factory=dict)   # anything else its starter passed for the executor (Session.start_task)

    @property
    def open(self) -> bool:
        return self.status in OPEN

    def public(self) -> dict:
        """What a client is told about it (the `task` event)."""
        return {"id": self.id, "kind": self.kind, "about": self.about, "status": self.status, "progress": self.progress,
                "question": self.question}


class Tell:
    """An executor's line back to the call while its task runs."""

    def __init__(self, session: Session, task: Task):
        self._s, self._t = session, task
        self._answer: asyncio.Future | None = None

    async def progress(self, text: str) -> None:
        """How far it has got, in a few words. Shown to the agent with its next line; nothing is said for it."""
        await self._s._task_progress(self._t, text)

    async def ask(self, question: str) -> str:
        """Something only the user can answer (may I run this, which of the two). The agent asks them at a moment of
        its choosing and passes the answer on; this returns it."""
        mine = self._answer = asyncio.get_running_loop().create_future()     # a new question replaces one still open
        await self._s._task_asks(self._t, question)
        try:
            return await mine
        finally:
            if self._answer is mine:
                self._answer = None
                self._s._task_resumed(self._t)     # answered, or the question fell away (answered somewhere else)

    def answer(self, text: str) -> bool:
        if self._answer is None or self._answer.done():
            return False
        self._answer.set_result(text)
        return True


class Executor(Protocol):
    describe: str        # one sentence for the responder: what this kind of task is for

    async def run(self, task: Task, tell: Tell) -> str:
        """Do it. Returns what came back ("" when nothing did); raises when it failed."""
        ...


class FunctionExecutor:
    """An executor from one async function: `fn(about, tell) -> str`."""

    def __init__(self, fn: Callable[[str, Tell], Awaitable[str]], describe: str):
        self.fn, self.describe = fn, describe

    async def run(self, task: Task, tell: Tell) -> str:
        return await self.fn(task.about, tell)


# ---------------------------------------------------------------------- what the responder writes
_ACTION = re.compile(r"^/(task|tell|stop|reported|任务|告诉|停|停止)(?=$|[ \t:：])[ \t:：]*(.*)$", re.I)   # a model that writes the verb in
                                                                                     # its own language is still obeyed
VERB = {"任务": "task", "告诉": "tell", "停": "stop", "停止": "stop"}
# the same action written as a tool call's argument, which a model trained to call tools sometimes does instead of the
# plain line it was asked for (Claude, 11-23: <parameter name="task">agent: count the files)
_AS_CALL = re.compile(r"""^<parameter\s+name=["'](task|tell|stop)["']\s*>[ \t]*(.*?)(?:</parameter>)?[ \t]*$""", re.I)


def action(line: str) -> tuple[str, str, str] | None:
    """A line of the responder's that is an action, not words: ("task", kind, about), ("tell", number, text) or
    ("stop", number, ""). None for anything else."""
    m = _ACTION.match((line or "").strip()) or _AS_CALL.match((line or "").strip())
    if not m:
        return None
    verb, rest = m.group(1).lower(), m.group(2).strip()
    verb = VERB.get(verb, verb)                    # /任务 agent: ... is a task, not something to say out loud
    head, _, tail = rest.replace("：", ":").partition(":")   # a full-width colon splits the kind just as well
    return verb, head.strip().lower(), tail.strip()


def written(line: str) -> str:
    """An action line as it is kept on the record: the plain form, however the responder wrote it."""
    verb, head, tail = action(line)
    return f"/{verb} {head}" + (f": {tail}" if tail else "")


# ---------------------------------------------------------------------- what the responder and Jev read
def _short(text: str, n: int = 80) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def entry(task: Task, limit: int = 1200) -> str:
    """The task's line on the call's record for what has just happened to it."""
    head = f"background task {task.id}"
    what = f"{task.kind}: {_short(task.about, 160)}"
    if task.status == RUNNING:
        return f"({head} started · {what})"
    if task.status == WAITING:
        return f"({head} is waiting on the user · {what} · it asks: {task.question})"
    if task.status == DONE:
        result = task.result if len(task.result) <= limit else task.result[:limit].rstrip() + " …"
        return f"({head} has come back · {what}\n{result})"
    if task.status == EMPTY:
        return f"({head} came back with nothing · {what})"
    if task.status == FAILED:
        return f"({head} failed · {what} · {_short(task.result, 200)})"
    return f"({head} was stopped · {what})"


def line(tasks: list[Task], clock: float, news: bool = True) -> str:
    """The tasks worth a place in the bracketed line: the ones still going, and — when `news` — the ones whose result is
    not told yet."""
    out = []
    for t in tasks:
        name = f'{t.id} {t.kind} "{_short(t.about)}"'
        if t.status == RUNNING:
            out.append(f"{name} running {max(0, clock - t.started):.0f} s" + (f', so far: "{_short(t.progress)}"' if t.progress else ""))
        elif t.status == WAITING:
            out.append(f'{name} waits on their answer: "{_short(t.question, 160)}"' + (", not asked yet" if t.news else ""))
        elif t.news and news:
            came = {DONE: "has come back", EMPTY: "came back with nothing", FAILED: "failed"}.get(t.status, t.status)
            out.append(f"{name} {came}, not told yet")
    return "; ".join(out)


def prompt(executors: dict[str, Executor]) -> str:
    """What the system prompt says about tasks, for the kinds this call has."""
    kinds = "\n".join(f"- {name}: {getattr(e, 'describe', '') or name}" for name, e in executors.items())
    return PROMPT.format(kinds=kinds)
