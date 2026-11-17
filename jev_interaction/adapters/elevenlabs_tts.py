from __future__ import annotations

import asyncio
import os
import time

import httpx

from ..latency import ms, observe


class ElevenLabsTTS:
    media_type = "audio/mpeg"

    def __init__(self, voice_id: str | None = None, model: str | None = None, api_key: str | None = None):
        self.voice = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "")
        self.model = model or os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")
        self.key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
        chunk_bytes = int(os.getenv("ELEVENLABS_TTS_CHUNK_BYTES", "0"))
        if chunk_bytes < 0:
            raise ValueError("ELEVENLABS_TTS_CHUNK_BYTES must be >= 0")
        self.chunk_bytes = chunk_bytes or None
        self.reuse_connection = os.getenv("ELEVENLABS_TTS_REUSE_CONNECTION", "1") != "0"
        self.prewarm = os.getenv("ELEVENLABS_TTS_PREWARM", "1") != "0"
        self._http: httpx.AsyncClient | None = None
        self._warm_task: asyncio.Task | None = None

    async def aclose(self):
        await self._stop_warmup()
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._warm_task = None

    def _client(self):
        if self._http is None:
            http = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=4, max_keepalive_connections=2,
                                                                   keepalive_expiry=60))
            if self.reuse_connection:
                self._http = http
        else:
            http = self._http
        return http

    def start_warmup(self):
        """One same-origin metadata GET, started by the call owner; never synthesizes placeholder speech."""
        if not self.prewarm or not self.reuse_connection:
            return None
        if self._warm_task is None:
            self._warm_task = asyncio.create_task(self._warmup())
        return self._warm_task

    async def _warmup(self):
        started = time.monotonic()
        result = {"ok": False, "outcome": "cancelled"}

        async def metadata():
            # Same synthesis origin/key. Metadata only; never send placeholder speech or follow redirects.
            # The documented endpoint may reject unauthenticated calls on the deployed service.
            async with self._client().stream("GET", "https://api.elevenlabs.io/v1/models",
                                             headers={"xi-api-key": self.key},
                                             timeout=httpx.Timeout(8, read=2)) as response:
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 256 * 1024:
                        return {"ok": False, "outcome": "body_limit"}
                return {"ok": response.is_success, "outcome": "complete", "http_status": response.status_code}

        try:
            result = await asyncio.wait_for(metadata(), 8)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - best-effort warmup must never prevent a real synthesis
            result = {"ok": False, "outcome": "failed", "error_type": type(exc).__name__}
        finally:
            result["elapsed_ms"] = ms(started)
            observe("tts_prewarm", **result)
        return result

    async def _stop_warmup(self):
        task = self._warm_task
        if task is not None:
            if not task.done():
                task.cancel()  # real speech has priority; do not queue behind a slow metadata request
            await asyncio.gather(task, return_exceptions=True)

    async def audio(self, text: str):
        await self._stop_warmup()
        http = self._client()
        try:
            async with http.stream("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}/stream?output_format=mp3_44100_128",
                                   headers={"xi-api-key": self.key}, json={"text": text, "model_id": self.model}) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(self.chunk_bytes):
                    yield chunk
        finally:
            if not self.reuse_connection:
                await http.aclose()
