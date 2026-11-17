"""One small, billed probe per selected provider using existing local settings. No text, audio or keys are saved.

    python tools/probe_voice_latency.py --live --llm --tts --output experiments/latency_20261117/live-probe.json

This measures components, not microphone-to-speaker latency. Run only when real provider calls are intended.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.adapters import registry  # noqa: E402
from jev_interaction.adapters.base import closing_stream  # noqa: E402
from jev_interaction.adapters.openai_compat import OpenAICompatResponder  # noqa: E402
from jev_interaction.latency import TimedSynthesizer, latency_scope  # noqa: E402
from jev_interaction.profile import Profile  # noqa: E402
from jev_interaction.server import paths  # noqa: E402


class Metrics:
    def __init__(self):
        self.rows = []

    def write(self, event, **fields):
        if event == "latency":
            self.rows.append(fields)


def failure(exc):
    # Provider bodies and arbitrary exception strings may contain settings. Keep just safe diagnostic fields.
    result = {"ok": False, "error_type": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        result["http_status"] = exc.response.status_code
    return result


async def llm_probe(timeout):
    rec, client, started, chunks = Metrics(), None, time.perf_counter(), 0
    try:
        client = OpenAICompatResponder(temperature=0)
        messages = [{"role": "user", "content": "请用两句简短中文说明语音助手能做什么，每句不超过十五个字，直接回答。"}]

        async def consume():
            nonlocal chunks
            with latency_scope(rec):
                async with closing_stream(client.lines(messages, max_tokens=64)) as stream:
                    async for _ in stream:
                        chunks += 1

        await asyncio.wait_for(consume(), timeout)
        result = {"ok": chunks > 0, "chunks": chunks}
    except Exception as exc:  # noqa: BLE001 - write bounded diagnostics, never a provider body or credentials
        result = failure(exc)
    finally:
        if client is not None:
            await client.aclose()
    return {**result, "elapsed_ms": round(1000 * (time.perf_counter() - started), 1), "stages": rec.rows}


async def tts_probe(timeout):
    rec, started, audio_bytes, first = Metrics(), time.perf_counter(), 0, None
    raw = None
    try:
        profile = Profile.load(paths.profiles()["companion"])
        voice = (profile.extra.get("voices") or {}).get(registry.selected("tts"))
        raw = registry.create("tts", voice=voice)
        synth = TimedSynthesizer(raw, rec, "probe", None)

        async def consume():
            nonlocal audio_bytes, first
            async with closing_stream(synth.audio("你好，我们开始吧。")) as stream:
                async for chunk in stream:
                    if chunk and first is None:
                        first = round(1000 * (time.perf_counter() - started), 1)
                    audio_bytes += len(chunk)

        await asyncio.wait_for(consume(), timeout)
        result = {"ok": audio_bytes > 0, "audio_bytes": audio_bytes, "first_audio_ms": first}
    except Exception as exc:  # noqa: BLE001
        result = failure(exc)
    finally:
        close = getattr(raw, "aclose", None)
        if close is not None:
            await close()
    return {**result, "elapsed_ms": round(1000 * (time.perf_counter() - started), 1), "stages": rec.rows}


async def run(args):
    paths.load_env()
    result = {"kind": "single real-provider component probe; NOT end-to-end or an A/B estimate",
              "date": time.strftime("%Y-%m-%d"), "timeout_s": args.timeout}
    # Sequential calls keep the two network measurements from competing with each other.
    if args.llm:
        result["llm"] = await llm_probe(args.timeout)
    if args.tts:
        result["tts"] = await tts_probe(args.timeout)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="allow the explicitly requested billed provider probes")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--tts", action="store_true")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if not args.live or not (args.llm or args.tts):
        parser.error("select --live and at least one of --llm / --tts")
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be > 0 and <= 60")
    result = json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2) + "\n"
    print(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
