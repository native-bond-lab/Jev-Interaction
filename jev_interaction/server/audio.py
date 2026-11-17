"""Call-owned, bounded audio replay: one provider stream serves preload, playback and range retries."""
from __future__ import annotations

import asyncio
from collections import OrderedDict

from ..adapters.base import closing_stream


class AudioGone(RuntimeError):
    """The line was interrupted, expired or evicted."""


class AudioLimitError(RuntimeError):
    """Synthesis exceeded this call's bounded audio storage."""


class AudioLine:
    def __init__(self, owner, line_id, text, synth, gen):
        self.owner, self.id, self.text, self.synth, self.gen = owner, line_id, text, synth, gen
        self.media_type = synth.media_type
        self.chunks: list[bytes] = []
        self.size, self.users = 0, 0
        self.done = self.cancelled = False
        self.error: Exception | None = None
        self.task: asyncio.Task | None = None
        self.changed = asyncio.Event()
        self.expiry = asyncio.get_running_loop().call_later(owner.ttl, self._expire)

    def start(self):
        if self.task is None and not self.cancelled:
            self.task = asyncio.create_task(self._produce())
            self.owner.tasks.add(self.task)
            self.task.add_done_callback(self.owner.tasks.discard)

    def _wake(self):
        previous, self.changed = self.changed, asyncio.Event()
        previous.set()

    def _expire(self):
        if self.users:
            self.expiry = asyncio.get_running_loop().call_later(self.owner.ttl, self._expire)
        else:
            self.owner.drop(self.id)

    async def _produce(self):
        try:
            async with self.owner.slots:
                async with closing_stream(self.synth.audio(self.text)) as stream:
                    async for chunk in stream:
                        if self.cancelled:
                            raise AudioGone()
                        if not chunk:
                            continue
                        if self.size + len(chunk) > self.owner.max_line_bytes:
                            raise AudioLimitError("Audio line exceeded byte limit")
                        self.owner.reserve(self, len(chunk))
                        self.chunks.append(bytes(chunk))
                        self.size += len(chunk)
                        self._wake()
        except asyncio.CancelledError:
            self.error = AudioGone()
        except Exception as exc:  # noqa: BLE001 - stored once; all readers see the same failure, with no paid retry
            self.error = exc
        finally:
            self.done = True
            self._wake()

    async def audio(self, text: str):
        self.users += 1
        index = 0
        try:
            self.start()
            while True:
                changed = self.changed
                if self.cancelled:
                    raise AudioGone()
                while index < len(self.chunks):
                    chunk = self.chunks[index]
                    index += 1
                    yield chunk
                    if self.cancelled:
                        raise AudioGone()
                if self.done:
                    if self.error is not None:
                        raise self.error
                    return
                await changed.wait()
        finally:
            self.users -= 1

    async def whole(self):
        return b"".join([chunk async for chunk in self.audio(self.text)])

    def cancel(self):
        self.cancelled = True
        self.expiry.cancel()
        self.owner.bytes -= self.size
        self.size = 0
        self.chunks.clear()
        self._wake()
        if self.task is not None and not self.task.done():
            self.task.cancel()


class CallAudio:
    def __init__(self, on_drop=lambda _: None, *, prefetch=True, max_lines=32, max_bytes=8 * 1024 * 1024,
                 max_line_bytes=2 * 1024 * 1024, concurrency=2, ttl=120):
        if min(max_lines, max_bytes, max_line_bytes, concurrency, ttl) <= 0:
            raise ValueError("Audio limits must be positive")
        self.on_drop, self.prefetch, self.ttl = on_drop, prefetch, ttl
        self.max_lines, self.max_bytes, self.max_line_bytes = max_lines, max_bytes, max_line_bytes
        self.slots = asyncio.Semaphore(concurrency)
        self.lines: OrderedDict[str, AudioLine] = OrderedDict()
        self.prefetched: OrderedDict[int, None] = OrderedDict()
        self.tasks: set[asyncio.Task] = set()
        self.bytes, self.closed = 0, False

    def add(self, line_id, text, synth, gen):
        if self.closed:
            raise AudioGone()
        if line_id in self.lines:
            return self.lines[line_id]
        while len(self.lines) >= self.max_lines:
            idle = next((old for old in self.lines.values() if old.done and not old.users), None)
            idle = idle or next((old for old in self.lines.values() if not old.users), None)
            if idle is None:
                raise AudioLimitError("All cached audio lines have active readers")
            self.drop(idle.id)
        line = self.lines[line_id] = AudioLine(self, line_id, text, synth, gen)
        # Only the first line of a reply starts speculatively. Later lines start when requested by the player.
        if self.prefetch and gen not in self.prefetched:
            self.prefetched[gen] = None
            while len(self.prefetched) > 64:
                self.prefetched.popitem(last=False)
            line.start()
        return line

    def reserve(self, line, count):
        if self.bytes + count > self.max_bytes:
            for old in list(self.lines.values()):
                if old is not line and old.done and not old.users:
                    self.drop(old.id)
                    if self.bytes + count <= self.max_bytes:
                        break
        if self.bytes + count > self.max_bytes:
            raise AudioLimitError("Call audio exceeded byte limit")
        self.bytes += count

    def drop(self, line_id):
        line = self.lines.pop(line_id, None)
        if line is not None:
            line.cancel()
            self.on_drop(line_id)

    def cancel_before(self, gen):
        for line in list(self.lines.values()):
            if line.gen < gen:
                self.drop(line.id)

    def finish_line(self, gen, playing_id):
        # Without a playback ACK, the server cannot identify which pending element the browser kept.
        if playing_id is not None:
            for line in list(self.lines.values()):
                if line.gen == gen and line.id != playing_id:
                    self.drop(line.id)

    async def close(self):
        self.closed = True
        for line_id in list(self.lines):
            self.drop(line_id)
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
