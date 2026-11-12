"""Alibaba Cloud Bailian (DashScope) CosyVoice: streaming speech synthesis for mainland China.

One WebSocket task per line: `run-task` (voice, format), wait for `task-started`, `continue-task` with the text,
`finish-task`; the audio arrives as binary frames until `task-finished`. Chunks are yielded as they come, so the
browser starts playing on the first one.

    DASHSCOPE_API_KEY=...   TTS_PROVIDER=dashscope   DASHSCOPE_TTS_VOICE=longxiaochun_v2 (cosyvoice-v2 voices:
    longxiaochun_v2 gentle female, longwan_v2 Mandarin female, longcheng_v2 bright male, ...)
"""
from __future__ import annotations

import json
import os
import uuid

import websockets

from .dashscope_asr import DASHSCOPE_WS


def tts_run_task(task_id: str, model: str, voice: str, sample_rate: int) -> dict:
    return {"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
            "payload": {"task_group": "audio", "task": "tts", "function": "SpeechSynthesizer", "model": model,
                        "parameters": {"text_type": "PlainText", "voice": voice, "format": "mp3", "sample_rate": sample_rate,
                                       "volume": 50, "rate": 1, "pitch": 1},
                        "input": {}}}


def tts_continue(task_id: str, text: str) -> dict:
    return {"header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {"text": text}}}


def tts_finish(task_id: str) -> dict:
    return {"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}


class CosyVoiceTTS:
    media_type = "audio/mpeg"

    def __init__(self, voice: str | None = None, model: str | None = None, api_key: str | None = None, sample_rate: int = 24000):
        self.voice = voice or os.getenv("DASHSCOPE_TTS_VOICE", "longxiaochun_v2")
        self.model = model or os.getenv("DASHSCOPE_TTS_MODEL", "cosyvoice-v2")
        self.key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.sr = sample_rate

    async def audio(self, text: str):
        task_id = uuid.uuid4().hex
        async with websockets.connect(DASHSCOPE_WS, additional_headers={"Authorization": f"bearer {self.key}"}, max_size=None) as ws:
            await ws.send(json.dumps(tts_run_task(task_id, self.model, self.voice, self.sr)))
            sent = False
            async for raw in ws:
                if isinstance(raw, bytes):
                    yield raw
                    continue
                m = json.loads(raw)
                event = (m.get("header") or {}).get("event")
                if event == "task-started" and not sent:
                    await ws.send(json.dumps(tts_continue(task_id, text)))
                    await ws.send(json.dumps(tts_finish(task_id)))
                    sent = True
                elif event == "task-failed":
                    raise RuntimeError(f"cosyvoice: {(m.get('header') or {}).get('error_message', m)}")
                elif event == "task-finished":
                    break
