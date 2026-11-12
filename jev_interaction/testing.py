"""Stand-ins for every provider, so a call runs with no keys: in tests, in examples, while writing a decision.

    from jev_interaction.testing import scripted_session
    session, events, judge = scripted_session({"floor": {"carry_on": 0.1, "yield": 0.9}})

The fake judge answers each question it is asked with the probabilities you give for that key (its choice is the
likeliest one) and keeps what it was asked; the fake responder says fixed lines; the fake recognizer yields what you put
on its queue; the fake VAD reports `voice`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .adapters.base import Segment
from .config import Config
from .profile import Profile
from .session import Session


class FakeJudge:
    def __init__(self, answers: dict[str, dict[str, float]] | None = None):
        self.answers, self.asked = dict(answers or {}), []

    async def ask(self, questions: dict, state: str) -> dict:
        self.asked.append((set(questions), state))
        return {k: {"choice": max(v, key=v.get), "probabilities": v} for k, v in self.answers.items() if k in questions}

    async def aclose(self) -> None: ...


class FakeRecognizer:
    def __init__(self):
        self.q: asyncio.Queue[Segment | None] = asyncio.Queue()

    def say(self, text: str) -> None:
        self.q.put_nowait(Segment(text))

    async def connect(self) -> None: ...
    async def send(self, pcm: bytes) -> None: ...

    async def close(self) -> None:
        self.q.put_nowait(None)

    async def segments(self):
        while (s := await self.q.get()) is not None:
            yield s


class FakeResponder:
    def __init__(self, lines=("Hey.", "What's up?")):
        self.seen: list[list[dict]] = []
        self.out = lines

    async def lines(self, messages: list[dict], max_tokens: int = 160):
        self.seen.append(messages)
        for x in self.out:
            yield x


class FakeVAD:
    def __init__(self):
        self.voice = False

    def is_voice(self, pcm: bytes) -> bool:
        return self.voice


class FakeSynthesizer:
    media_type = "audio/mpeg"

    async def audio(self, text: str):
        yield text.encode("utf-8")


def scripted_session(answers: dict | None = None, policies: dict | None = None, profile: Profile | None = None,
                     send: Callable[[dict], Awaitable[None]] | None = None, **config) -> tuple[Session, list[dict], FakeJudge]:
    """A session on fakes, plus the list its events land in and its judge. `config` overrides Config fields."""
    events: list[dict] = []

    async def collect(e: dict) -> None:
        events.append(e)
        if send:
            await send(e)
    cfg = Config(policies={**Config().policies, **(policies or {})}, **{"opening_turns": 0, **config})
    judge = FakeJudge(answers)
    s = Session(profile or Profile("Mara Quinn", task="A companion who chats.", manner="Chatty listener."), send=collect,
                judge=judge, recognizer=FakeRecognizer(), responder=FakeResponder(), vad=FakeVAD(), config=cfg)
    return s, events, judge


FakeASR, FakeLLM = FakeRecognizer, FakeResponder     # the names the tests used
