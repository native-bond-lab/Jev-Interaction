"""Call-local latency observations. No extra text, keys, network requests or public protocol messages.

All server durations use monotonic time. Playback ACKs include their return trip and are a proxy for, not an exact
measurement of, device output. An optional browser duration uses its own clock; clock origins are never subtracted.
"""
from __future__ import annotations

import math
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar

from .adapters.base import closing_stream

_TRACE = ContextVar("jev_latency_trace", default=None)


@contextmanager
def latency_scope(recorder, **ids):
    token = _TRACE.set((recorder, ids))
    try:
        yield
    finally:
        _TRACE.reset(token)


def observe(stage: str, **fields):
    trace = _TRACE.get()
    if trace is not None:
        recorder, ids = trace
        recorder.write("latency", stage=stage, **ids, **fields)


def ms(since: float, now: float | None = None) -> float:
    return round(1000 * ((time.monotonic() if now is None else now) - since), 1)


class CallTimings:
    def __init__(self, recorder):
        self.rec = recorder
        self.voice_at = self.asr_at = None
        self.replies: OrderedDict[int, dict] = OrderedDict()
        self.lines: OrderedDict[str, dict] = OrderedDict()

    def open_utterance(self):
        self.voice_at = self.asr_at = None

    def voice(self, received_at: float):
        self.voice_at = received_at

    def asr_final(self, utt: int):
        self.asr_at = time.monotonic()
        fields = {"last_voice_to_asr_final_ms": ms(self.voice_at, self.asr_at)} if self.voice_at is not None else {}
        self.rec.write("latency", stage="asr_final", utt=utt, **fields)

    def reply(self, gen: int, kind: str, answers_user: bool):
        self.replies[gen] = {"at": time.monotonic(), "kind": kind, "n": 0, "played": False,
                             "voice": self.voice_at if answers_user else None, "asr": self.asr_at if answers_user else None}
        while len(self.replies) > 64:
            self.replies.popitem(last=False)

    def line(self, gen: int, line_id: str):
        reply = self.replies[gen]
        reply["n"] += 1
        now = time.monotonic()
        self.lines[line_id] = {"at": now, "gen": gen, "played": False}
        while len(self.lines) > 256:
            self.lines.popitem(last=False)
        fields = {f"{key}_to_line_ms": ms(reply[key], now) for key in ("voice", "asr") if reply[key] is not None}
        self.rec.write("latency", stage="line_sent", gen=gen, id=line_id, first=reply["n"] == 1,
                       response_to_line_ms=ms(reply["at"], now), **fields)

    def playback(self, msg: dict):
        line_id = msg.get("id")
        if not isinstance(line_id, str):
            return
        line = self.lines.get(line_id)
        if line is None or msg.get("gen") != line["gen"] or line["played"]:
            return
        reply = self.replies.get(line["gen"])
        if reply is None:
            return
        now = time.monotonic()
        fields = {f"{key}_to_playback_ack_ms": ms(reply[key], now) for key in ("voice", "asr") if reply[key] is not None}
        client_ms = msg.get("client_receive_to_play_ms")
        if type(client_ms) in (int, float) and math.isfinite(client_ms) and 0 <= client_ms <= 3_600_000:
            fields["client_receive_to_play_ms"] = round(client_ms, 1)
        self.rec.write("latency", stage="playback_start", gen=line["gen"], id=msg["id"], first=not reply["played"],
                       response_to_playback_ack_ms=ms(reply["at"], now), line_to_playback_ack_ms=ms(line["at"], now), **fields)
        line["played"] = reply["played"] = True


class TimedSynthesizer:
    """Observe the existing lazy synthesis route without starting extra synthesis or changing its lifetime."""
    def __init__(self, synth, recorder, line_id: str, gen: int | None, ready_at: float | None = None):
        self.synth, self.rec, self.id, self.gen = synth, recorder, line_id, gen
        self.media_type = synth.media_type
        self.ready_at = ready_at

    async def audio(self, text: str):
        started, first, complete = time.monotonic(), True, False
        fields = {"line_to_tts_request_ms": ms(self.ready_at, started)} if self.ready_at is not None else {}
        self.rec.write("latency", stage="tts_request", id=self.id, gen=self.gen, **fields)
        try:
            async with closing_stream(self.synth.audio(text)) as stream:
                async for chunk in stream:
                    if chunk and first:
                        fields = {"line_to_first_audio_ms": ms(self.ready_at)} if self.ready_at is not None else {}
                        self.rec.write("latency", stage="tts_first_audio", id=self.id, gen=self.gen,
                                       request_to_first_audio_ms=ms(started), **fields)
                        first = False
                    yield chunk
            complete = True
        finally:
            self.rec.write("latency", stage="tts_end", id=self.id, gen=self.gen, complete=complete,
                           had_audio=not first, duration_ms=ms(started))
