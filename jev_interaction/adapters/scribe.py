"""ElevenLabs Scribe realtime: streaming recognition that closes a segment after a short silence (VAD commit)."""
from __future__ import annotations

import asyncio
import base64
import json
import os

import websockets

from .base import Segment


class ScribeRealtime:
    def __init__(self, language: str = "en", model: str | None = None, silence_s: float = 0.35,
                 api_key: str | None = None, sample_rate: int = 16000):
        model = model or os.getenv("ELEVENLABS_ASR_MODEL", "scribe_v2_realtime")
        self.url = (f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id={model}&audio_format=pcm_{sample_rate}"
                    f"&commit_strategy=vad&vad_silence_threshold_secs={silence_s}" + (f"&language_code={language}" if language else ""))
        self.key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        self.sr = sample_rate
        self.ws = None
        self.queue: asyncio.Queue[Segment | None] = asyncio.Queue()

    async def connect(self):
        self.ws = await websockets.connect(self.url, additional_headers={"xi-api-key": self.key}, max_size=None)
        asyncio.create_task(self._recv())

    async def _recv(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m.get("message_type") == "committed_transcript" and (m.get("text") or "").strip():
                    await self.queue.put(Segment(m["text"].strip()))
        finally:
            await self.queue.put(None)

    async def send(self, pcm: bytes):
        if self.ws is not None:
            await self.ws.send(json.dumps({"message_type": "input_audio_chunk", "audio_base_64": base64.b64encode(pcm).decode(),
                                           "commit": False, "sample_rate": self.sr}))

    async def segments(self):
        while (seg := await self.queue.get()) is not None:
            yield seg

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
