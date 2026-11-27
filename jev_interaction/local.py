"""The call on this computer's own microphone and speakers: no page, no window.

A harness that starts the call server (connectors/) has no browser to put the call in. This is the client instead: it
opens the call on the server's own socket as a page would (docs/protocol.md), sends the microphone as 200 ms frames,
plays each line through the speakers as it is synthesized, and tells the server what was playing when it is told to
stop. It runs inside the call server (JEV_LOCAL_AUDIO=1) and needs `pip install "jev-interaction[local]"` (miniaudio).

What a page has and this has not: echo cancellation. With speakers on, the microphone hears the agent's own voice. The
engine raises its bar for a voice while a line plays and drops recognized words that are the agent's own, and the
microphone stays open throughout: closing it (as JEV_LOCAL_ECHO=mute once did) made an interruption impossible to hear
and, with a long line queued, left the call deaf until the line ended. Headphones make the echo moot.

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


def encoded(miniaudio, media: str):
    """The decoder for a synthesizer's media type; None for raw PCM16, which needs none. Whatever provider the user
    chose, its audio is played: nothing here assumes one vendor's format."""
    media = (media or "").lower()
    if "pcm" in media or "l16" in media:
        return None
    for mark, fmt in (("wav", miniaudio.FileFormat.WAV), ("flac", miniaudio.FileFormat.FLAC), ("ogg", miniaudio.FileFormat.VORBIS),
                      ("vorbis", miniaudio.FileFormat.VORBIS)):
        if mark in media:
            return fmt
    return miniaudio.FileFormat.MP3


def raw(source, media: str):
    """Raw PCM16 mono at the rate its media type names (24 kHz unless it says otherwise), as the speakers' rate."""
    import re
    m = re.search(r"rate=(\d+)", media or "")
    rate, step = int(m.group(1)) if m else RATE, 4800
    while True:
        pcm = source.read(step)
        if not pcm:
            return
        if rate != RATE:                          # the nearest sample: enough for a voice, and no dependency
            import array
            x = array.array("h", pcm[:len(pcm) // 2 * 2])
            n = len(x) * RATE // rate
            pcm = array.array("h", (x[min(len(x) - 1, i * rate // RATE)] for i in range(n))).tobytes()
        yield pcm


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


def _louder(pcm: bytes, target: float, max_gain: float) -> bytes:
    """Bring a frame up towards `target` RMS, never past `max_gain`, clipping instead of wrapping.

    A laptop microphone at 200 RMS is inaudible to both the local VAD and the recognizer; the same speech at 3000 is
    heard by both. Silence is left alone: there is nothing to amplify.
    """
    import array
    import math

    samples = array.array("h", pcm[: len(pcm) // 2 * 2])
    if not samples:
        return pcm
    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    if rms < 30 or rms >= target:
        return pcm
    gain = min(max_gain, target / rms)
    for i, x in enumerate(samples):
        y = int(x * gain)
        samples[i] = 32767 if y > 32767 else (-32768 if y < -32768 else y)
    return samples.tobytes()


class LocalCall:
    def __init__(self, port: int, profile: str | None = None, language: str | None = None, recorder=None):
        self.port = port
        dump_path = os.getenv("JEV_DUMP_MIC")     # 诊断：把送给识别的音频原样存盘
        self.dump = open(dump_path, "wb") if dump_path else None
        trace_path = os.getenv("JEV_TRACE_PLAYBACK")   # 诊断：每 2 秒记一次播放状态
        self.trace = open(trace_path, "a", encoding="utf-8") if trace_path else None
        if recorder is None:
            from .recorder import Recorder
            recorder = Recorder(None)
        self.rec = recorder
        self.traced = 0.0
        self.profile, self.language = (profile, language or "en") if profile else profile_for(language)
        self.mute = False                         # kept for callers that set it; nothing closes the microphone now
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
            """The line's encoded audio: a decoder waits only a bounded time for another piece."""

            def __init__(self, pieces: queue.Queue, status: dict):
                self.pieces, self.status = pieces, status
                self.kept, self.ended = b"", False

            def read(self, n: int) -> bytes:
                while len(self.kept) < n and not self.ended:
                    try:
                        piece = self.pieces.get(timeout=LocalCall.NEXT_CHUNK_TIMEOUT_S)
                    except queue.Empty:
                        self.status["error"] = "timed out waiting for the next audio chunk"
                        self.pieces.put_nowait(None)
                        self.ended = True
                        break
                    if piece is None:
                        self.ended = True
                        break
                    self.kept += piece
                out, self.kept = self.kept[:n], self.kept[n:]
                return out
        while True:
            line = await self.lines.get()
            mine = self.current = {**line, "done": False}
            self.speaker.played = 0
            last_error, heard = "", False
            for attempt in range(1, self.PLAY_ATTEMPTS + 1):
                if self.current is not mine:
                    break
                if attempt > 1:
                    self.speaker.clear()
                    self.rec.write("tts_playback", what="retry", attempt=attempt, text=line["text"][:80])
                mine["attempt"] = attempt
                status = {"done": False, "error": ""}
                chunks: queue.Queue = queue.Queue()
                kind: queue.Queue = queue.Queue(maxsize=1)
                source = Source(chunks, status)

                def decode(mine=mine, status=status, source=source, told=kind, attempt=attempt):
                    try:
                        media = told.get()
                        fmt = encoded(miniaudio, media)
                        if fmt is None:
                            for pcm in raw(source, media):
                                if self.current is not mine or mine.get("attempt") != attempt:
                                    return
                                self.speaker.feed(pcm)
                            return
                        for pcm in miniaudio.stream_any(source, source_format=fmt, nchannels=1, sample_rate=RATE,
                                                        output_format=miniaudio.SampleFormat.SIGNED16, frames_to_read=RATE // 20):
                            if self.current is not mine or mine.get("attempt") != attempt:
                                return
                            self.speaker.feed(pcm.tobytes())
                    except Exception as exc:  # noqa: BLE001 - decoding failure is bounded and may be retried once
                        status["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                    finally:
                        status["done"] = True

                threading.Thread(target=decode, daemon=True).start()

                async def fetch(mine=mine, line=line, kind=kind, chunks=chunks, attempt=attempt):
                    try:
                        async with http.stream("GET", f"http://127.0.0.1:{self.port}{line['audio']}",
                                               timeout=min(self.NEXT_CHUNK_TIMEOUT_S, self.RETRY_IDLE_TIMEOUT_S)) as r:
                            kind.put(r.headers.get("content-type", "audio/mpeg"))
                            pieces = r.aiter_bytes().__aiter__()
                            while True:
                                try:
                                    piece = await asyncio.wait_for(pieces.__anext__(), self.RETRY_IDLE_TIMEOUT_S)
                                except StopAsyncIteration:
                                    break
                                if self.current is not mine or mine.get("attempt") != attempt:
                                    return
                                chunks.put(piece)
                    finally:
                        if kind.empty():
                            kind.put("audio/mpeg")
                        chunks.put(None)

                try:
                    mine["fetching"] = True
                    try:
                        await fetch()
                    finally:
                        mine["fetching"] = False
                    if self.current is not mine:
                        break
                    heard = await self._wait_for_playback(mine, status)
                    if heard and not status["error"]:
                        break
                    last_error = status["error"] or "audio decode or playback stalled"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - a broken or stalled stream gets one bounded retry
                    last_error = f"{type(exc).__name__}: {str(exc)[:120]}"
                self.rec.write("tts_playback", what="attempt failed", attempt=attempt, error=last_error)
                if attempt < self.PLAY_ATTEMPTS:
                    continue
                break
            if self.current is mine and heard:
                self.heard.append(line["text"])
                self.current = None
            elif self.current is mine:
                self.speaker.clear()
                self.current = None
                self.rec.write("tts_playback", what="line ended without audio",
                               error=last_error or "both audio attempts failed")

    async def _send_ws(self, message) -> None:
        await asyncio.wait_for(self.ws.send(message), self.WS_SEND_TIMEOUT_S)

    async def _events(self, ws) -> None:
        async for raw in ws:
            if isinstance(raw, str) and not await self._on(json.loads(raw)):
                return

    async def _supervise(self, jobs: dict) -> None:
        """A dead microphone worker must end the call, not leave an open but deaf websocket."""
        tasks = {name: asyncio.create_task(coro) for name, coro in jobs.items()}
        try:
            done, _ = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)
            for name, task in tasks.items():
                if task not in done:
                    continue
                if task.cancelled():
                    error = asyncio.CancelledError()
                else:
                    error = task.exception()
                if error is not None:
                    self.rec.write("local_call", what="worker failed", worker=name,
                                   error=f"{type(error).__name__}: {str(error)[:160]}")
                    raise error
                if name != "events":
                    error = RuntimeError(f"{name} worker stopped unexpectedly")
                    self.rec.write("local_call", what="worker stopped", worker=name, error=str(error))
                    raise error
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    CAPTURE_IDLE_S = 4.0
    CAPTURE_CHECK_S = 0.25
    CAPTURE_RETRY_S = 1.0
    NEXT_CHUNK_TIMEOUT_S = 8.0
    RETRY_IDLE_TIMEOUT_S = 8.0
    PLAY_ATTEMPTS = 2
    WS_SEND_TIMEOUT_S = 5.0
    WS_CLOSE_TIMEOUT_S = 2.0

    async def _capture(self, miniaudio, frames: asyncio.Queue, device_id, loop) -> None:
        """Keep the selected input device flowing; silence from the device is distinct from ASR keepalive silence."""
        while True:
            capture = None
            mic = None
            try:
                capture = miniaudio.CaptureDevice(
                    input_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=16000,
                    buffersize_msec=100, device_id=device_id)

                def microphone():
                    while True:
                        data = yield
                        self._last_capture_at = time.monotonic()
                        loop.call_soon_threadsafe(frames.put_nowait, bytes(data))

                mic = microphone()
                next(mic)
                self._last_capture_at = time.monotonic()
                capture.start(mic)
                self.rec.write("local_call", what="capture started", device_id=device_id)
                while True:
                    await asyncio.sleep(self.CAPTURE_CHECK_S)
                    idle = time.monotonic() - self._last_capture_at
                    if idle >= self.CAPTURE_IDLE_S:
                        self.rec.write("local_call", what="capture stalled; restarting",
                                       device_id=device_id, idle_s=round(idle, 2))
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a failed device is reopened with the same selection
                self.rec.write("local_call", what="capture failed; restarting", device_id=device_id,
                               error=f"{type(exc).__name__}: {str(exc)[:160]}")
            finally:
                if capture is not None:
                    try:
                        capture.close()
                    except Exception as exc:  # noqa: BLE001 - report cleanup errors and keep the recovery loop alive
                        self.rec.write("local_call", what="capture close failed",
                                       error=f"{type(exc).__name__}: {str(exc)[:120]}")
                if mic is not None:
                    try:
                        mic.close()
                    except Exception as exc:  # noqa: BLE001 - cleanup must not silence future restart attempts
                        self.rec.write("local_call", what="capture callback close failed",
                                       error=f"{type(exc).__name__}: {str(exc)[:120]}")
            await asyncio.sleep(self.CAPTURE_RETRY_S)

    async def _wait_for_playback(self, mine: dict, status: dict) -> bool:
        """Wait for the line to finish, or for the device to stop pulling from the buffer.

        The second case is what left the call believing it was still talking: the buffer never drained, so the line never
        ended, so it never answered and never spoke on its own again — until the call was restarted."""
        last_played, moved_at = self.speaker.played, time.monotonic()
        while self.current is mine:
            if status["done"] and self.speaker.waiting() == 0:
                return not status["error"]
            now = time.monotonic()
            if self.speaker.played != last_played:
                last_played, moved_at = self.speaker.played, now
            elif now - moved_at > self.STALLED_S:
                self.speaker.clear()
                return False
            await asyncio.sleep(0.03)
        return False

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
                await self._send_ws(json.dumps({"type": "heard", "gen": self.gen, "text": "\n".join([*self.heard, part]).strip()}, ensure_ascii=False))
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

    STARVED_S = 3.0       # a line with this long of nothing buffered and nothing queued is over, not playing
    STALLED_S = 3.0       # a buffer the device has not pulled from for this long is dead, not playing

    async def _report(self) -> None:
        """Tell the call when the speakers start and when they have run empty, as a page does."""
        quiet_since = time.monotonic()
        starved_since = None
        while True:
            await asyncio.sleep(0.05)
            if (self.current is not None and not self.current.get("fetching")
                    and self.speaker.waiting() == 0 and self.lines.empty()):
                starved_since = starved_since or time.monotonic()
                if time.monotonic() - starved_since >= self.STARVED_S:
                    # The line's fetch or decode stopped without finishing: stop counting it as playing, or the call
                    # believes it is talking forever and never speaks on its own again.
                    self.current = None
                    starved_since = None
            else:
                starved_since = None
            sounding = (self.current is not None
                        and (self.speaker.waiting() > 0 or self.speaker.played > 0))
            if sounding:
                quiet_since = None
                if not self.playing:
                    self.playing = True
                    await self._send_ws(json.dumps({"type": "playback", "state": "playing"}))
            elif self.playing:
                quiet_since = quiet_since or time.monotonic()
                if time.monotonic() - quiet_since > 0.15:
                    self.playing = False
                    await self._send_ws(json.dumps({"type": "playback", "state": "idle"}))
            if self.trace is not None and time.monotonic() - getattr(self, "traced", 0) > 2.0:
                self.traced = time.monotonic()
                try:
                    self.trace.write(f"{time.strftime('%H:%M:%S')} playing={self.playing} sounding={sounding} "
                                     f"current={bool(self.current)} waiting={self.speaker.waiting()} "
                                     f"queued={self.lines.qsize()} played={self.speaker.played}\n")
                    self.trace.flush()
                except OSError:
                    pass

    # ---- the microphone in
    KEEPALIVE_S = 0.5     # no frame from the device for this long: send silence, the recognizer times out on a gap
    TARGET_RMS = 3000.0   # a quiet microphone is the commonest reason nothing is heard: bring speech up to this level
    MAX_GAIN = 8.0        # at most +18 dB, so room noise is not blown up into speech

    async def _mic(self, frames: asyncio.Queue) -> None:
        buf = bytearray()
        while True:
            try:
                buf += await asyncio.wait_for(frames.get(), self.KEEPALIVE_S)
            except asyncio.TimeoutError:
                buf += b"\x00" * FRAME          # the stream must never be quiet for eight seconds, or the session ends
            while len(buf) >= FRAME:
                frame = _louder(bytes(buf[:FRAME]), self.TARGET_RMS, self.MAX_GAIN)
                del buf[:FRAME]
                if self.dump is not None:       # JEV_DUMP_MIC: exactly what the recognizer is fed, for a real call
                    self.dump.write(frame)
                await self._send_ws(frame)

    async def once(self) -> None:
        """One call, from picking up to its end (the socket closing, or the server saying it is not ready)."""
        import httpx
        import miniaudio
        import websockets
        loop, frames = asyncio.get_running_loop(), asyncio.Queue()
        try:
            ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/ws", max_size=None, proxy=None)
        except TypeError:
            ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/ws", max_size=None)
        self.ws = ws
        capture_id = device("capture", os.getenv("JEV_LOCAL_MIC"))
        playback = miniaudio.PlaybackDevice(output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=RATE, buffersize_msec=60,
                                            device_id=device("playback", os.getenv("JEV_LOCAL_SPEAKER")))
        try:
            await self._send_ws(json.dumps({"type": "start", "profile": self.profile, "language": self.language}))
            out = self.speaker.stream()
            next(out)
            playback.start(out)
            async with httpx.AsyncClient(trust_env=False, timeout=30) as http:        # this machine: never a proxy
                await self._supervise({"playback": self._play(http), "report": self._report(),
                                       "microphone": self._mic(frames),
                                       "capture": self._capture(miniaudio, frames, capture_id, loop),
                                       "events": self._events(ws)})
        finally:
            self._drop()
            playback.close()
            try:
                await asyncio.wait_for(ws.close(), self.WS_CLOSE_TIMEOUT_S)
            except asyncio.TimeoutError:
                self.rec.write("local_call", what="websocket close timed out")

    async def run(self) -> None:
        """Stay on the line: a call that ends (the server not set up yet, a dropped socket) is picked up again."""
        try:
            while True:
                try:
                    await self.once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - no device, no server yet: try again shortly
                    self.rec.write("local_call", what=f"call dropped: {type(exc).__name__}: {str(exc)[:160]}")
                    print(f"call dropped ({type(exc).__name__}: {exc}); picking it up again", flush=True)
                await asyncio.sleep(3.0)
        finally:
            if self.dump is not None:
                self.dump.close()
            if self.trace is not None:
                self.trace.close()
            self.rec.close()


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
