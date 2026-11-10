from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass
class Segment:
    """Words the recognizer closed after a short pause."""
    text: str
    final: bool = True


class VAD(Protocol):
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
    async def audio(self, text: str) -> AsyncIterator[bytes]:
        """Encoded audio for a line, streamed (the client starts playing on the first chunk)."""
        ...

    media_type: str
