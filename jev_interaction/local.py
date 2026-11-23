"""The call on this computer's own microphone and speakers: no page, no window.

A harness that starts the call server (connectors/) has no browser to put the call in. This is the client instead: it
opens the call on the server's own socket as a page would (docs/protocol.md), sends the microphone as 200 ms frames,
plays each line through the speakers as it is synthesized, and tells the server what was playing when it is told to
stop. It runs inside the call server (JEV_LOCAL_AUDIO=1) and needs `pip install "jev-interaction[local]"` (miniaudio).

What a page has and this has not: echo cancellation. With speakers on, the microphone hears the agent's own voice. The
engine already raises its bar for a voice while a line plays and drops recognized words that are the agent's own; with
JEV_LOCAL_ECHO=mute the microphone is closed while a line plays instead (nothing of its own is heard, and the user
cannot talk over it). Headphones need neither.

The devices are the computer's defaults; JEV_LOCAL_MIC and JEV_LOCAL_SPEAKER name others (a part of the name is enough).
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time

RATE = 24000                     # what lines are decoded to and played at
FRAME = 6400                     # 200 ms of 16 kHz mono PCM16: what the call takes from the microphone


def profile_for(language: str | None = None) -> tuple[str, str]:
    """(persona, language) for the call: JEV_LOCAL_PROFILE, or the desk companion in the user's language."""
    lang = (language or os.getenv("JEV_LANGUAGE") or os.getenv("LANG") or "en").lower()
    zh = lang.startswith("zh")
    return os.getenv("JEV_LOCAL_PROFILE") or ("pet_zh" if zh else "pet"), "zh" if zh else "en"


def device(kind: str, name: str | None):
    """The id of the capture or playback device whose name has `name` in it; None for the default (or no such one)."""
    if not name:
        return None
    import miniaudio
    found = miniaudio.Devices().get_captures() if kind == "capture" else miniaudio.Devices().get_playbacks()
    return next((d["id"] for d in found if name.lower() in d["name"].lower()), None)


class Speaker:
    """What the speakers are given: a buffer the audio thread drains, silence when it is empty."""

    def __init__(self):
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.played = 0                           # bytes of the current line that have gone out

    def feed(self, pcm: bytes) -> None:
        with self.lock:
            self.buf += pcm

    def clear(self) -> None:
        with self.lock:
            self.buf.clear()

    def waiting(self) -> int:
        with self.lock:
            return len(self.buf)

    def stream(self):
        """The generator miniaudio's playback device pulls from (it sends the number of frames it wants)."""
        frames = yield b""
        while True:
            want = frames * 2
            with self.lock:
                out = bytes(self.buf[:want])
                del self.buf[:want]
            self.played += len(out)
            frames = yield out + b"\x00" * (want - len(out))


class LocalCall:
    def __init__(self, port: int, profile: str | None = None, language: str | None = None):
        self.port = port
        self.profile, self.language = (profile, language or "en") if profile else profile_for(language)
        self.mute = (os.getenv("JEV_LOCAL_ECHO") or "").lower() == "mute"
        self.speaker = Speaker()
        self.lines: asyncio.Queue = asyncio.Queue()       # lines waiting to be played, in order
        self.gen: int | None = None
        self.current: dict | None = None          # the line playing: {gen, text, done, bytes}
        self.heard: list[str] = []                # the lines of this reply that played to their end
        self.playing = False
        self.ws = None

    # ---- lines out
    async def _play(self, http) -> None:
        """One line at a time: fetched as it is synthesized, decoded as it arrives, played as it is decoded."""
        import miniaudio

        class Source(miniaudio.StreamableSource):
            """The line's encoded audio as the decoder reads it: the pieces fetched so far, waited for when it runs dry."""

            def __init__(self, pieces: queue.Queue):
                self.pieces, self.kept, self.ended = pieces, b"", False

            def read(self, n: int) -> bytes:
                while len(self.kept) < n and not self.ended:
                    piece = self.pieces.get()
                    if piece is None:             # the last of it: from here a read gives what is left, then nothing
                        self.ended = True
                        break
                    self.kept += piece
                out, self.kept = self.kept[:n], self.kept[n:]
                return out
        while True:
            line = await self.lines.get()
            self.current = {**line, "done": False}
            self.speaker.played = 0
            chunks: queue.Queue = queue.Queue()

            def decode(mine=self.current, source=Source(chunks)):
                try:
                    for pcm in miniaudio.stream_any(source, source_format=miniaudio.FileFormat.MP3, nchannels=1, sample_rate=RATE,
                                                    output_format=miniaudio.SampleFormat.SIGNED16, frames_to_read=RATE // 20):
                        if self.current is not mine:
                            return                # stopped: the rest of it is not for the speakers
                        self.speaker.feed(pcm.tobytes())
                except Exception:  # noqa: BLE001 - a stream cut short ends where it ends
                    pass
                finally:
                    mine["done"] = True
            threading.Thread(target=decode, daemon=True).start()
            try:
                async with http.stream("GET", f"http://127.0.0.1:{self.port}{line['audio']}") as r:
                    async for piece in r.aiter_bytes():
                        chunks.put(piece)
            except Exception:  # noqa: BLE001 - the synthesizer failed: this line is not heard, the call goes on
                pass
            finally:
                chunks.put(None)
            mine = self.current
            while self.current is mine and not (mine["done"] and self.speaker.waiting() == 0):
                await asyncio.sleep(0.03)
            if self.current is mine:              # it played to its end
                self.heard.append(line["text"])
                self.current = None

    def _heard_so_far(self) -> str:
        """As much of the line playing as has gone out, by the page's own measure: its speaking rate."""
        line = self.current
        if line is None:
            return ""
        text, at = line["text"], self.speaker.played / (RATE * 2)
        per = 0.2 if any("一" <= c <= "鿿" for c in text) else 0.065
        return text[:int(len(text) * min(1.0, at / max(1.0, len(text) * per)))]

    async def _on(self, e: dict) -> bool:
        """One event from the call. False when the call is over."""
        kind = e.get("type")
        if kind == "line":
            if e.get("gen") != self.gen:
                self.gen, self.heard = e.get("gen"), []
            self.lines.put_nowait({"gen": e.get("gen"), "text": _plain(e.get("text") or ""), "audio": e["audio"]})
        elif kind == "listen" and e.get("audio") and not self.playing:
            self.lines.put_nowait({"gen": None, "text": "", "audio": e["audio"]})      # a sound slipped in, not a reply
        elif kind == "stop":
            part = self._heard_so_far() if self.current and self.current.get("gen") == self.gen else ""
            self._drop()
            if self.gen is not None:
                await self.ws.send(json.dumps({"type": "heard", "gen": self.gen, "text": "\n".join([*self.heard, part]).strip()}, ensure_ascii=False))
        elif kind == "finish_line":
            while not self.lines.empty():
                self.lines.get_nowait()
        elif kind in ("hangup", "busy"):
            return False
        elif kind == "error" and e.get("what") in ("settings", "start"):
            return False
        return True

    def _drop(self) -> None:
        while not self.lines.empty():
            self.lines.get_nowait()
        self.current = None
        self.speaker.clear()

    async def _report(self) -> None:
        """Tell the call when the speakers start and when they have run empty, as a page does."""
        quiet_since = time.monotonic()
        while True:
            await asyncio.sleep(0.05)
            sounding = self.current is not None or self.speaker.waiting() > 0 or not self.lines.empty()
            if sounding:
                quiet_since = None
                if not self.playing:
                    self.playing = True
                    await self.ws.send(json.dumps({"type": "playback", "state": "playing"}))
            elif self.playing:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since > 0.15:
                    self.playing = False
                    await self.ws.send(json.dumps({"type": "playback", "state": "idle"}))

    # ---- the microphone in
    async def _mic(self, frames: asyncio.Queue) -> None:
        buf = bytearray()
        while True:
            buf += await frames.get()
            while len(buf) >= FRAME:
                frame = bytes(buf[:FRAME])
                del buf[:FRAME]
                if self.mute and (self.playing or self.speaker.waiting()):
                    frame = b"\x00" * FRAME       # the line is playing: the microphone is closed to it
                await self.ws.send(frame)

    async def once(self) -> None:
        """One call, from picking up to its end (the socket closing, or the server saying it is not ready)."""
        import httpx
        import miniaudio
        import websockets
        loop, frames = asyncio.get_running_loop(), asyncio.Queue()

        def microphone():
            while True:
                data = yield
                loop.call_soon_threadsafe(frames.put_nowait, bytes(data))
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/ws", max_size=None, proxy=None)
        except TypeError:
            ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/ws", max_size=None)
        self.ws = ws
        capture = miniaudio.CaptureDevice(input_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=16000, buffersize_msec=100,
                                          device_id=device("capture", os.getenv("JEV_LOCAL_MIC")))
        playback = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=RATE, buffersize_msec=60,
                                            device_id=device("playback", os.getenv("JEV_LOCAL_SPEAKER")))
        jobs = []
        try:
            await ws.send(json.dumps({"type": "start", "profile": self.profile, "language": self.language}))
            mic = microphone()
            next(mic)
            capture.start(mic)
            out = self.speaker.stream()
            next(out)
            playback.start(out)
            async with httpx.AsyncClient(trust_env=False, timeout=30) as http:        # this machine: never a proxy
                jobs = [loop.create_task(c) for c in (self._play(http), self._report(), self._mic(frames))]
                async for raw in ws:
                    if isinstance(raw, str) and not await self._on(json.loads(raw)):
                        break
        finally:
            for j in jobs:
                j.cancel()
            self._drop()
            capture.close()
            playback.close()
            await ws.close()

    async def run(self) -> None:
        """Stay on the line: a call that ends (the server not set up yet, a dropped socket) is picked up again."""
        while True:
            try:
                await self.once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - no device, no server yet: try again shortly
                pass
            await asyncio.sleep(3.0)


def _plain(text: str) -> str:
    from .speaking import plain
    return plain(text)


def available() -> str:
    """"" when this computer's microphone and speakers can be used, or why not."""
    try:
        import miniaudio  # noqa: F401
    except ImportError:
        return 'the microphone and speakers need one more package: pip install "jev-interaction[local]"'
    return ""
