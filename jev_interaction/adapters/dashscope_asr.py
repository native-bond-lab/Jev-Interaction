"""Alibaba Cloud Bailian (DashScope) Paraformer realtime: streaming recognition for mainland China.

One WebSocket per call (wss://dashscope.aliyuncs.com/api-ws/v1/inference): `run-task`, wait for `task-started`, stream
binary PCM, read `result-generated` events, `finish-task` at the end. A sentence that the service closes (after
`max_sentence_silence` of quiet) becomes one Segment, the same shape ScribeRealtime produces.

    DASHSCOPE_API_KEY=...   ASR_PROVIDER=dashscope   (DASHSCOPE_ASR_MODEL defaults to paraformer-realtime-v2)
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import websockets

from .base import Segment

DASHSCOPE_WS = os.getenv("DASHSCOPE_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")


def run_task(task_id: str, model: str, sample_rate: int, languages: list[str], silence_ms: int) -> dict:
    return {"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
            "payload": {"task_group": "audio", "task": "asr", "function": "recognition", "model": model,
                        "parameters": {"format": "pcm", "sample_rate": sample_rate, "language_hints": languages,
                                       "max_sentence_silence": silence_ms, "heartbeat": True},
                        "input": {}}}


def finish_task(task_id: str) -> dict:
    return {"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}


def closed_sentence(message: dict) -> str | None:
    """The text of a sentence the service has closed, from one server event; None for partials and other events."""
    header, payload = message.get("header") or {}, message.get("payload") or {}
    if header.get("event") != "result-generated":
        return None
    sentence = (payload.get("output") or {}).get("sentence") or {}
    done = sentence.get("sentence_end") is True or (sentence.get("sentence_end") is None and sentence.get("end_time") is not None)
    text = (sentence.get("text") or "").strip()
    return text if done and text else None


class ParaformerRealtime:
    def __init__(self, language: str = "zh", model: str | None = None, silence_ms: int = 400, api_key: str | None = None,
                 sample_rate: int = 16000):
        self.model = model or os.getenv("DASHSCOPE_ASR_MODEL", "paraformer-realtime-v2")
        self.languages = ["zh", "en"] if language in ("zh", "", None) else [language, "en"]
        self.silence_ms = silence_ms
        self.key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.sr = sample_rate
        self.task_id = uuid.uuid4().hex
        self.ws = None
        self.started = asyncio.Event()
        self.queue: asyncio.Queue[Segment | None] = asyncio.Queue()

    async def connect(self):
        self.ws = await websockets.connect(DASHSCOPE_WS, additional_headers={"Authorization": f"bearer {self.key}"}, max_size=None)
        await self.ws.send(json.dumps(run_task(self.task_id, self.model, self.sr, self.languages, self.silence_ms)))
        asyncio.create_task(self._recv())
        await asyncio.wait_for(self.started.wait(), timeout=10)

    async def _recv(self):
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                m = json.loads(raw)
                event = (m.get("header") or {}).get("event")
                if event == "task-started":
                    self.started.set()
                elif event == "task-failed":
                    self.started.set()
                    raise RuntimeError(f"paraformer: {(m.get('header') or {}).get('error_message', m)}")
                elif (text := closed_sentence(m)) is not None:
                    await self.queue.put(Segment(text))
                elif event == "task-finished":
                    break
        finally:
            await self.queue.put(None)

    async def send(self, pcm: bytes):
        if self.ws is not None and self.started.is_set():
            await self.ws.send(pcm)

    async def segments(self):
        while (seg := await self.queue.get()) is not None:
            yield seg

    async def close(self):
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps(finish_task(self.task_id)))
            finally:
                await self.ws.close()
