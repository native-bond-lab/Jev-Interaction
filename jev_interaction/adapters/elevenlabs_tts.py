from __future__ import annotations

import os

import httpx


class ElevenLabsTTS:
    media_type = "audio/mpeg"

    def __init__(self, voice_id: str | None = None, model: str = "eleven_v4_turbo", api_key: str | None = None):
        self.voice = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "")
        self.model = model
        self.key = api_key or os.getenv("ELEVENLABS_API_KEY", "")

    async def audio(self, text: str):
        async with httpx.AsyncClient(timeout=30) as http:
            async with http.stream("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}/stream?output_format=mp3_44100_128",
                                   headers={"xi-api-key": self.key}, json={"text": text, "model_id": self.model}) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(4096):
                    yield chunk
