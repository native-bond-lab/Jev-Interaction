"""Doubao HTTP V3 SSE: decode and yield each audio event immediately, keeping one HTTP pool per call/voice.

Official protocol: docs.volcengine.com/docs/doubao-voice/http-chunked-sse-unidirectional-streaming-v3
No undocumented metadata warmup is attempted. The server's shared synthesis/prefetch layer applies normally.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid

import httpx

from .doubao import auth_headers

TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse"
DEFAULT_RESOURCE = "seed-tts-2.0"                 # speech-synthesis 2.0: the voices ..._uranus_bigtts belong to it


class DoubaoTTS:
    media_type = "audio/mpeg"

    def __init__(self, voice=None):
        self.voice = voice or os.getenv("DOUBAO_TTS_VOICE", "")
        self.resource = os.getenv("DOUBAO_TTS_RESOURCE_ID") or DEFAULT_RESOURCE
        if not self.voice:
            raise ValueError("set DOUBAO_TTS_VOICE to the enabled voice")
        self.headers = auth_headers()
        self._http = None

    async def aclose(self):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def audio(self, text):
        if self._http is None:
            self._http = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30, connect=10),
                                           limits=httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=60))
        headers = {**self.headers, "X-Api-Resource-Id": self.resource, "X-Api-Request-Id": str(uuid.uuid4())}
        body = {"user": {"uid": "jev-interaction"}, "req_params": {
            "text": text, "speaker": self.voice, "audio_params": {"format": "mp3", "sample_rate": 24000}}}
        async with self._http.stream("POST", TTS_URL, headers=headers, json=body) as response:
            response.raise_for_status()
            lines, complete = response.aiter_lines(), False
            async for raw in lines:
                # The selected endpoint is SSE; ignore event names, keepalives and blank delimiters.
                if not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                    code = event["code"]
                    if type(code) is not int:
                        raise ValueError("Invalid status type")
                    encoded = event.get("data")
                    chunk = base64.b64decode(encoded, validate=True) if encoded else b""
                except (ValueError, TypeError, KeyError) as exc:
                    raise RuntimeError("Invalid Doubao TTS audio event") from exc
                if code not in (0, 20000000):
                    # Do not expose provider bodies: they may echo text or credentials.
                    raise RuntimeError(f"Doubao TTS error code {int(code)}")
                if chunk:
                    yield chunk
                if code == 20000000:
                    complete = True
                    # Fully consume the short HTTP tail so the next sentence can reuse this socket.
                    async def drain():
                        for _ in range(32):
                            try:
                                await anext(lines)
                            except StopAsyncIteration:
                                return

                    try:
                        await asyncio.wait_for(drain(), 0.25)
                    except (asyncio.TimeoutError, httpx.HTTPError):
                        pass  # audio already completed; closing this response discards the damaged socket
                    break
            if not complete:
                raise RuntimeError("Doubao TTS stream ended without completion")
