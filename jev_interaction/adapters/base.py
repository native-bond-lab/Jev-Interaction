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
    revises: bool = False        # the same sentence, said a little longer: replace the one held, do not add a new one


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
        """Yield encoded audio chunks as the provider produces them; never buffer a whole line before the first yield.

        The shared player feeds each chunk to its decoder as it arrives and starts output as soon as the decoder can
        produce PCM. A provider may pause between chunks, but each wait is bounded by the player's stream timeout.
        """
        ...


class SoundModel(Protocol):
    """Has the user finished, from the sound of their voice alone (adapters/smart_turn.py): `score` gets the last
    seconds of the line from the user (16 kHz PCM16, the pause so far included) and returns p(the turn is over), or
    None while the model is not ready. It runs in a worker thread, once per frame of a pause. The turn decision weighs
    it with the words (Config.sound_rule)."""
    @property
    def ready(self) -> bool: ...
    def warm(self) -> None: ...
    def score(self, pcm: bytes) -> float | None: ...


class Embedder(Protocol):
    """Speaker embeddings for the caller's voiceprint (voiceprint.py). `embed` runs in a worker thread; it returns a
    unit-length vector, or None while the model is not ready or the clip is too short."""
    @property
    def ready(self) -> bool: ...
    def warm(self) -> None: ...
    def embed(self, pcm: bytes): ...
