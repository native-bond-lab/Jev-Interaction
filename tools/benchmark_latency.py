"""Offline SSE experiment on the actual responder. No real model, TTS, microphone or provider requests.

    python tools/benchmark_latency.py --output experiments/latency_20261117/offline-stream.json

Both modes receive identical delayed chunks. The numbers measure only text ready for synthesis in this controlled
stream, not live end-to-end latency. A single-sentence control must show no claimed streaming gain.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from unittest.mock import patch

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.adapters.openai_compat import OpenAICompatResponder  # noqa: E402

CASES = {
    "zh_late_newline": ["可以的。", "我们先检查输入链路，", "再看模型生成，", "然后检查语音合成，", "最后检查播放缓冲。", "\n"],
    "en_late_newline": ["Yes, we can. ", "Let's check the microphone, ", "then the model, ", "then synthesis, ", "and finally playback.", "\n"],
    "single_sentence_control": ["我们", "先检查", "输入", "链路", "和播放。", "\n"],
    "newline_control": ["可以的。\n", "我们先检查输入。", "\n"],
}


class ScriptedSSE(httpx.AsyncByteStream):
    def __init__(self, deltas, delay):
        self.deltas, self.delay = deltas, delay

    async def __aiter__(self):
        for delta in self.deltas:
            await asyncio.sleep(self.delay)
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": delta}}]}) + "\n\n").encode()
        yield b"data: [DONE]\n\n"


async def measure(mode, deltas, delay):
    # Explicit fake URL/key/model and a MockTransport: saved settings and credentials are never loaded or used.
    with patch.dict(os.environ, {"LLM_CHUNK_MODE": mode, "LLM_EXTRA_BODY": "{}", "LLM_REUSE_CONNECTION": "1"}):
        llm = OpenAICompatResponder("https://latency.invalid/v1", "offline-test", "offline-test")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=ScriptedSSE(deltas, delay))))
    started, first, out = time.perf_counter(), None, []
    try:
        async for line in llm.lines([]):
            if first is None:
                first = round(1000 * (time.perf_counter() - started), 1)
            out.append(line)
    finally:
        await llm.aclose()
    assert "".join("".join(out).split()) == "".join("".join(deltas).split()), "spoken content changed"
    return {"first_synthesizable_text_ms": first, "chunks": len(out)}


async def run(delay):
    results = {}
    for name, deltas in CASES.items():
        before = await measure("newline", deltas, delay)
        after = await measure("first_sentence", deltas, delay)
        results[name] = {"newline": before, "first_sentence": after,
                         "saved_ms": round(before["first_synthesizable_text_ms"] - after["first_synthesizable_text_ms"], 1)}
    return {"kind": "offline simulated SSE; NOT live end-to-end latency", "delta_delay_ms": 1000 * delay, "cases": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay-ms", type=float, default=100)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if not 0 < args.delay_ms <= 5000:
        parser.error("--delay-ms must be > 0 and <= 5000")
    result = asyncio.run(run(args.delay_ms / 1000))
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(body)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
