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

    def hear(self, text: str) -> None:
        """The words so far of a piece the user is still saying (a recognizer's partial result)."""
        self.q.put_nowait(Segment(text, final=False))

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


class FakeEmbedder:
    """Speaker embeddings for tests: the voice is the clip's first byte, so callers pick it by filling frames with it.
    Voices 1 and 2 are near each other (the same person); any other byte is a different person."""
    ready = True

    def warm(self) -> None:
        pass

    def embed(self, pcm: bytes):
        import numpy as np
        if len(pcm) < 800 * 32:
            return None
        v = np.zeros(8, dtype=np.float32)
        v[0 if pcm[0] in (1, 2) else pcm[0] % 7 + 1] = 1.0
        v[7] += 0.2 if pcm[0] == 2 else 0.0
        return v / np.linalg.norm(v)


class FakeSeer:
    """Eyes for tests: says the next of the sentences it was given for each picture ("" = nothing new), keeps what it saw."""
    def __init__(self, *said: str):
        self.said, self.looked = list(said), []

    async def describe(self, image: bytes, media_type: str = "image/jpeg", *, before: str = "", before_image: bytes | None = None,
                       name: str = "", language: str = "English") -> str:
        self.looked.append((image, before, before_image))
        return self.said.pop(0) if self.said else ""


class FakeSynthesizer:
    media_type = "audio/mpeg"

    async def audio(self, text: str):
        yield text.encode("utf-8")


def scripted_session(answers: dict | None = None, policies: dict | None = None, profile: Profile | None = None,
                     send: Callable[[dict], Awaitable[None]] | None = None, embedder=None, seer=None, **config) -> tuple[Session, list[dict], FakeJudge]:
    """A session on fakes, plus the list its events land in and its judge. `config` overrides Config fields."""
    events: list[dict] = []

    async def collect(e: dict) -> None:
        events.append(e)
        if send:
            await send(e)
    cfg = Config(policies={**Config().policies, **(policies or {})}, **{"opening_turns": 0, **config})
    judge = FakeJudge(answers)
    s = Session(profile or Profile("Mara Quinn", task="A companion who chats.", manner="Chatty listener."), send=collect,
                judge=judge, recognizer=FakeRecognizer(), responder=FakeResponder(), vad=FakeVAD(), config=cfg,
                embedder=embedder, seer=seer)
    return s, events, judge


FakeASR, FakeLLM = FakeRecognizer, FakeResponder     # the names the tests used
