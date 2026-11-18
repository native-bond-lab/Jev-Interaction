from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Segment:
    """Words the recognizer closed after a short pause; or, with `final` False, the words so far of the piece the user
    is in the middle of (a recognizer that has them may send them; the session only uses them while the user talks over
    the agent's line, to ask Jev before the pause comes)."""
    text: str
    final: bool = True


class VAD(Protocol):
    """`is_voice` is all a detector needs. One that also has `voiced_ms(pcm, playing) -> int` is asked that instead:
    how much of the frame is voice, with its bar raised while the agent's own line is playing."""
    def is_voice(self, pcm: bytes) -> bool: ...


class Recognizer(Protocol):
    async def connect(self) -> None: ...
    async def send(self, pcm: bytes) -> None: ...
    def segments(self) -> AsyncIterator[Segment]: ...
    async def close(self) -> None: ...


class Responder(Protocol):
    def lines(self, messages: list[dict], max_tokens: int) -> AsyncIterator[str]:
        """The agent's reply, one spoken line at a time, as soon as each line is complete."""
        ...


class Synthesizer(Protocol):
    media_type: str

    def audio(self, text: str) -> AsyncIterator[bytes]:
        """Encoded audio for a line, streamed (the client starts playing on the first chunk); usually an async generator."""
        ...


class Embedder(Protocol):
    """Speaker embeddings for the caller's voiceprint (voiceprint.py). `embed` runs in a worker thread; it returns a
    unit-length vector, or None while the model is not ready or the clip is too short."""
    @property
    def ready(self) -> bool: ...
    def warm(self) -> None: ...
    def embed(self, pcm: bytes): ...


class Seer(Protocol):
    """The agent's eyes (adapters/vision.py): a picture the page took because the view changed, as one plain sentence
    of what is new in it against `before_image` (the picture looked at last, None for the first look: then the scene
    itself), or "" when nothing worth a word is."""
    async def describe(self, image: bytes, media_type: str = "image/jpeg", *, before: str = "", before_image: bytes | None = None,
                       moving_s: float = 0.0, name: str = "", language: str = "English") -> str: ...
