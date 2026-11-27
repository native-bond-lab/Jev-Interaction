"""Doubao streaming ASR V3 binary WebSocket protocol, one connection for the entire call.

Official protocol: docs.volcengine.com/docs/doubao-voice/large-model-streaming-automatic-speech-recognition-api-1
200 ms PCM16 frames match the existing server protocol. Definite utterances alone trigger normal turn decisions;
partial text is available for overlap detection. No speculative model calls or automatic reconnect/replay.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import struct
import uuid
import zlib

import websockets

from .base import Segment
from .doubao import auth_headers

ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
MAX_PACKET = 4 * 1024 * 1024
DEFAULT_RESOURCE = "volc.seedasr.sauc.duration"    # streaming-ASR 2.0: what a console key is granted for it


def packet(payload: bytes, *, audio=False, last=False):
    encoded = gzip.compress(payload, mtime=0)
    return bytes([0x11, (0x20 if audio else 0x10) | (2 if last else 0), 0x01 if audio else 0x11, 0]) + struct.pack(">I", len(encoded)) + encoded


def unpack(data: bytes):
    if len(data) < 8 or len(data) > MAX_PACKET or data[0] >> 4 != 1:
        raise RuntimeError("Invalid Doubao ASR packet")
    offset, kind, flags = (data[0] & 15) * 4, data[1] >> 4, data[1] & 15
    if offset < 4 or offset + 4 > len(data) or kind not in (9, 15):
        raise RuntimeError("Invalid Doubao ASR header")
    code = None
    if kind == 15 or flags & 1:
        if offset + 8 > len(data):
            raise RuntimeError("Truncated Doubao ASR header")
        code = struct.unpack_from(">I", data, offset)[0] if kind == 15 else None
        offset += 4
    size = struct.unpack_from(">I", data, offset)[0]
    payload = data[offset + 4:]
    if len(payload) != size:
        raise RuntimeError("Truncated Doubao ASR payload")
    if kind == 15:
        raise RuntimeError(f"Doubao ASR error code {code}")
    if data[2] & 15 == 1:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decoder.decompress(payload, MAX_PACKET + 1)
        if len(payload) > MAX_PACKET or not decoder.eof:
            raise RuntimeError("Doubao ASR payload exceeds limit or is truncated")
    elif data[2] & 15:
        raise RuntimeError("Unsupported Doubao ASR compression")
    if data[2] >> 4 != 1:
        raise RuntimeError("Unsupported Doubao ASR serialization")
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Invalid Doubao ASR JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Invalid Doubao ASR result")
    return result, bool(flags & 2)


class Utterances:
    """Full result snapshots repeat earlier utterances; emit each finalized start-time only once."""
    def __init__(self):
        self.last_start = self.last_end = -1
        self.partial = ""
        self.dropped = 0          # kept for the log; no longer a reason to drop anything
        self.seen = []            # (start, text) already emitted: repeats are dropped, a rewound clock is not
        self.last_definite = None  # (start, text) of the last finished sentence: a longer copy of it is a revision
        self.stale = 0
        self.stale_text = ""      # the rejected sentence itself: repeated snapshots of one must count once

    def feed(self, event):
        result = event.get("result") or {}
        if not isinstance(result, dict):
            raise RuntimeError("Invalid Doubao ASR result structure")
        segments, partial = [], []
        for utterance in result.get("utterances") or []:
            text = (utterance.get("text") or "").strip()
            if not text:
                continue
            start, end = utterance.get("start_time"), utterance.get("end_time")
            if type(start) is not int or type(end) is not int:
                # An utterance still being said may arrive without times: it is text, not a reason to kill the stream
                # (raising here ended recognition for the rest of every call that got one).
                if text and not utterance.get("definite"):
                    partial.append(text)
                continue
            key = (start, text)
            if key in self.seen:
                continue                              # 这句已经定稿过了（服务端会把整段快照反复发来）
            if utterance.get("definite") is True:
                # 只有定稿才登记：否则同一句的中间结果会把这个位置占掉，定稿反而被跳过
                revises = bool(self.last_definite and self.last_definite[0] == start
                               and text.startswith(self.last_definite[1]) and text != self.last_definite[1])
                self.last_definite = (start, text)
                self.seen.append(key)
                if len(self.seen) > 64:
                    self.seen.pop(0)
                segments.append(Segment(text, revises=revises))
                self.last_start, self.last_end = start, max(self.last_end, end)
                self.stale = 0
                self.stale_text = ""
            else:
                partial.append(text)
        # Time watermarks reject old snapshots without retaining the transcript or an ever-growing set.
        text = "".join(partial)
        if text and text != self.partial:
            segments.append(Segment(text, final=False))
        self.partial = text
        return segments


class DoubaoRealtime:
    def __init__(self, language="zh"):
        self.resource = os.getenv("DOUBAO_ASR_RESOURCE_ID") or DEFAULT_RESOURCE
        self.silence_ms = int(os.getenv("DOUBAO_ASR_SILENCE_MS", "400"))
        if self.silence_ms < 200:
            raise ValueError("DOUBAO_ASR_SILENCE_MS must be >= 200")
        self.headers = auth_headers(asr=True)
        self.ws = self.task = None
        self.queue = asyncio.Queue(maxsize=64)
        self.error = None
        self.closed = False
        self.finished = False                   # the call is over: the consumer is told, a replaced stream is not
        self.utterances = Utterances()

    async def connect(self):
        connect_id = str(uuid.uuid4())
        headers = {**self.headers, "X-Api-Resource-Id": self.resource, "X-Api-Connect-Id": connect_id,
                   "X-Api-Request-Id": connect_id, "X-Api-Sequence": "-1"}
        try:
            self.ws = await websockets.connect(ASR_URL, additional_headers=headers, max_size=MAX_PACKET, open_timeout=10)
            request = {"user": {"uid": "jev-interaction"}, "audio": {"format": "pcm", "codec": "raw", "rate": 16000,
                       "bits": 16, "channel": 1}, "request": {"model_name": "bigmodel", "enable_itn": True,
                       "enable_punc": True, "show_utterances": True, "result_type": "full", "end_window_size": self.silence_ms}}
            await self.ws.send(packet(json.dumps(request).encode()))
            # Await the full-request acknowledgement so invalid credentials/settings fail call setup promptly.
            event, last = unpack(await asyncio.wait_for(self.ws.recv(), 10))
            self._deliver(event)
            if last:
                raise RuntimeError("Doubao ASR closed during setup")
            self.task = asyncio.create_task(self._recv())
        except BaseException:
            await self.close()
            raise

    async def restart(self) -> None:
        """A stream that went quiet while audio still came in: open a fresh one, keeping what the caller built up."""
        await self.close(final=False)           # the consumer stays: only the stream is replaced
        self.closed, self.finished, self.error = False, False, None
        self.utterances = Utterances()          # the timestamps start over with the stream
        await self.connect()

    def _deliver(self, event):
        for segment in self.utterances.feed(event):
            try:
                self.queue.put_nowait(segment)
            except asyncio.QueueFull:
                raise RuntimeError("Doubao ASR consumer fell behind") from None

    async def _recv(self):
        try:
            async for raw in self.ws:
                event, last = unpack(raw)
                self._deliver(event)
                if last:
                    break
            if not self.closed:
                raise RuntimeError("Doubao ASR stream closed during call")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - communicate failure to the segment consumer and next send
            self.error = RuntimeError(f"Doubao ASR receive failed ({type(exc).__name__}: {str(exc)[:160]})")   # the code matters
        finally:
            if self.error is not None or self.finished:   # an error is handed on; a stream being replaced is not the end
                if self.queue.full():
                    self.queue.get_nowait()
                self.queue.put_nowait(None)

    SEND_TIMEOUT_S = 2.0      # a stream that stops reading must not hold the call: the frame is dropped, not awaited

    async def send(self, pcm):
        if self.error is not None:
            raise self.error
        if self.ws is not None and not self.closed:
            try:
                await asyncio.wait_for(self.ws.send(packet(pcm, audio=True)), self.SEND_TIMEOUT_S)
            except asyncio.TimeoutError:
                # The vendor stopped reading: the socket buffer is full and the write would never return. Mark the
                # stream dead so the caller drops the frame and the watchdog reopens it.
                self.error = RuntimeError("Doubao ASR send stalled (the stream stopped reading)")
                raise self.error from None

    async def segments(self):
        while (segment := await self.queue.get()) is not None:
            yield segment
        if self.error is not None:
            raise self.error

    async def close(self, final: bool = True):
        """`final`: the call is over, so the consumer is told there is nothing more (a fresh stream is not the end)."""
        if self.closed:
            return
        self.closed, self.finished = True, final
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.ws is not None:
            try:
                # Closing does not await a final transcript or hold up hangup on model work.
                await asyncio.wait_for(self.ws.send(packet(b"", audio=True, last=True)), 0.25)
            except Exception:  # noqa: BLE001 - already disconnected or cancelled
                pass
            finally:
                await self.ws.close()
                self.ws = None
        if final:                               # the call is over: the consumer is told there is nothing more
            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(None)
