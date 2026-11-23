"""Speech from any service that speaks the OpenAI audio API, so a provider is the user's choice and not ours:
OpenAI itself, Groq, SiliconFlow, a Whisper or a Kokoro server on this machine, and whoever else serves
`/audio/speech` and `/audio/transcriptions`.

    TTS_PROVIDER=openai-compatible    TTS_BASE_URL, TTS_API_KEY, TTS_MODEL, TTS_VOICE
    ASR_PROVIDER=openai-compatible    ASR_BASE_URL, ASR_API_KEY, ASR_MODEL

The synthesizer streams a line as the service encodes it (TTS_FORMAT: mp3 by default).

The recognizer is not a streaming one: that API takes a finished clip. So the clips are cut here, on the quiet after a
stretch of voice (`pause_ms`), and each is sent whole; its words come back as one closed segment. What this costs
against a streaming recognizer: no words until the pause, so nothing to judge while the user is still talking over a
line. It is the price of working with every provider there is.

Not checked against a real service yet: written to the published API and tested against a stand-in.
"""
from __future__ import annotations

import asyncio
import io
import os
import wave

import httpx

from ..utterance import frame_db
from .base import Segment

MEDIA = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "opus": "audio/ogg", "aac": "audio/aac", "pcm": "audio/pcm;rate=24000"}


class OpenAICompatTTS:
    def __init__(self, voice: str | None = None, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 fmt: str | None = None, transport=None, **_):
        self.base_url = (base_url or os.getenv("TTS_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.getenv("TTS_API_KEY", "")
        self.model = model or os.getenv("TTS_MODEL", "")
        self.voice = voice or os.getenv("TTS_VOICE", "")
        if not self.base_url or not self.model:
            raise ValueError("set TTS_BASE_URL and TTS_MODEL (any endpoint that serves /audio/speech, and one of its models)")
        self.fmt = (fmt or os.getenv("TTS_FORMAT") or "mp3").lower()
        self.media_type = MEDIA.get(self.fmt, "audio/mpeg")
        self.transport = transport                # a stand-in for the network, in tests

    async def audio(self, text: str):
        body = {"model": self.model, "input": text, "response_format": self.fmt, **({"voice": self.voice} if self.voice else {})}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        async with httpx.AsyncClient(timeout=30, transport=self.transport) as http:
            async with http.stream("POST", f"{self.base_url}/audio/speech", headers=headers, json=body) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(4096):
                    yield chunk


class OpenAICompatASR:
    """A recognizer over `/audio/transcriptions`: voice is gathered until a pause, the clip is sent, its words are a
    closed segment. Clips are transcribed one at a time, so the segments come out in the order they were said."""

    def __init__(self, language: str = "en", base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 sample_rate: int = 16000, pause_ms: int = 400, min_voice_ms: int = 200, transport=None, **_):
        self.base_url = (base_url or os.getenv("ASR_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.getenv("ASR_API_KEY", "")
        self.model = model or os.getenv("ASR_MODEL", "")
        if not self.base_url or not self.model:
            raise ValueError("set ASR_BASE_URL and ASR_MODEL (any endpoint that serves /audio/transcriptions, and one of its models)")
        self.language, self.rate, self.pause_ms, self.min_voice_ms = language, sample_rate, pause_ms, min_voice_ms
        self.transport = transport
        self.out: asyncio.Queue[Segment | None] = asyncio.Queue()
        self.clips: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.clip, self.before = bytearray(), b""         # the stretch being said; the frame before it began
        self.voice_ms = self.quiet_ms = 0
        self.floor = -60.0                        # the room's own level, followed while nobody talks
        self.worker: asyncio.Task | None = None
        self.http: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self.http = httpx.AsyncClient(timeout=30, transport=self.transport)
        self.worker = asyncio.get_running_loop().create_task(self._transcribe())

    async def send(self, pcm: bytes) -> None:
        ms, db = len(pcm) * 1000 // (self.rate * 2), frame_db(pcm)
        if db > max(self.floor + 12.0, -50.0):    # a voice: well over the room
            if not self.clip:
                self.clip += self.before          # the frame before it, so its first sound is not clipped
            self.clip += pcm
            self.voice_ms, self.quiet_ms = self.voice_ms + ms, 0
        elif self.clip:
            self.clip += pcm
            self.quiet_ms += ms
            if self.quiet_ms >= self.pause_ms:    # they paused: this stretch is a clip
                if self.voice_ms >= self.min_voice_ms:
                    self.clips.put_nowait(bytes(self.clip))
                self.clip, self.voice_ms, self.quiet_ms = bytearray(), 0, 0
        else:
            self.floor = 0.9 * self.floor + 0.1 * db
        self.before = pcm

    def wav(self, pcm: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(pcm)
        return buf.getvalue()

    async def _transcribe(self) -> None:
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        while (clip := await self.clips.get()) is not None:
            try:
                r = await self.http.post(f"{self.base_url}/audio/transcriptions", headers=headers,
                                         files={"file": ("clip.wav", self.wav(clip), "audio/wav")},
                                         data={"model": self.model, "language": self.language, "response_format": "json"})
                r.raise_for_status()
                text = (r.json().get("text") or "").strip()
            except Exception:  # noqa: BLE001 - a clip the service refused is words not heard; the call goes on
                text = ""
            if text:
                self.out.put_nowait(Segment(text))

    async def segments(self):
        while (s := await self.out.get()) is not None:
            yield s

    async def close(self) -> None:
        self.clips.put_nowait(None)
        if self.worker is not None:
            try:
                await asyncio.wait_for(self.worker, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.worker.cancel()
        if self.http is not None:
            await self.http.aclose()
        self.out.put_nowait(None)
