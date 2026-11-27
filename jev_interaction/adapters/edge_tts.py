"""Edge TTS: the speech Microsoft Edge reads pages with, through a plain WebSocket. No key, no account.

`edge-tts` speaks the same service the browser does (a `wss://speech.platform.bing.com` endpoint with a fixed public
token), so it is free and needs no registration; the audio comes back as MP3 in chunks, which is exactly what the client's
player wants.

Audio is handed on as the service produces it. If a reply ends suspiciously early, it is asked for once more and only
the missing suffix is appended when the retry contains the first stream as its prefix.
"""
from __future__ import annotations

import os

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"       # a natural female Mandarin voice; EDGE_TTS_VOICE overrides it

# What one character of Chinese speech weighs in this service's MP3: measured 1,290–1,970 bytes a character over real
# lines. Anything under this is a stream that was cut off, not a short line.
BYTES_PER_CHAR = 400
MIN_RETRY_TEXT = 2                           # below this many characters the check says nothing useful


class EdgeTTS:
    media_type = "audio/mpeg"

    def __init__(self, voice: str | None = None):
        self.voice = voice or os.getenv("EDGE_TTS_VOICE") or DEFAULT_VOICE
        self.rate = os.getenv("EDGE_TTS_RATE", "+0%")
        self.pitch = os.getenv("EDGE_TTS_PITCH", "+0Hz")

    async def aclose(self) -> None:
        """Kept for the factory's shape: every line uses its own connection."""

    async def _once(self, text: str) -> bytes:
        import edge_tts

        blob = b""
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                blob += chunk["data"]
        return blob

    async def audio(self, text: str):
        blob = b""
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                data = chunk["data"]
                blob += data
                yield data
        wanted = len(text.strip()) * BYTES_PER_CHAR
        if len(text.strip()) >= MIN_RETRY_TEXT and len(blob) < wanted:
            again = await self._once(text)          # cut off: ask once more before the call goes silent
            if len(again) > len(blob):
                if again.startswith(blob):
                    yield again[len(blob):]
                # A retry can differ in container headers. Do not play a second copy of the first attempt.
