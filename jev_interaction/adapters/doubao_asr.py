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
                raise RuntimeError("Doubao ASR utterance is missing timestamps")
            if start <= self.last_start or end <= self.last_end:
                continue
            if utterance.get("definite") is True:
                segments.append(Segment(text))
                self.last_start = start
                self.last_end = max(self.last_end, end)
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
        self.resource = os.getenv("DOUBAO_ASR_RESOURCE_ID", "")
        if not self.resource:
            raise ValueError("set DOUBAO_ASR_RESOURCE_ID to the enabled streaming ASR resource")
        self.silence_ms = int(os.getenv("DOUBAO_ASR_SILENCE_MS", "400"))
        if self.silence_ms < 200:
            raise ValueError("DOUBAO_ASR_SILENCE_MS must be >= 200")
        self.headers = auth_headers(asr=True)
        self.ws = self.task = None
        self.queue = asyncio.Queue(maxsize=64)
        self.error = None
        self.closed = False
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
            self.error = RuntimeError(f"Doubao ASR receive failed ({type(exc).__name__})")
        finally:
            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(None)

    async def send(self, pcm):
        if self.error is not None:
            raise self.error
        if self.ws is not None and not self.closed:
            await self.ws.send(packet(pcm, audio=True))

    async def segments(self):
        while (segment := await self.queue.get()) is not None:
            yield segment
        if self.error is not None:
            raise self.error

    async def close(self):
        if self.closed:
            return
        self.closed = True
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
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(None)
