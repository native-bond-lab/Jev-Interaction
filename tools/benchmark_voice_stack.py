"""Sequential component samples for ANY configured LLM/TTS pair; no ASR or device playback measurement.

    python tools/benchmark_voice_stack.py --live --trials 5 --output experiments/stack.json

Keeps the production LLM and TTS adapters alive across trials, separating the first call from later calls.
Uses existing settings; no warmup, settings edits or automatic proxy changes. One short LLM and one short TTS
request per trial. Saves stage timings/configuration identity, never generated text/audio/keys. Three consecutive
failures in either component stop sampling. Use separate output files for different stacks.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.adapters.base import closing_stream  # noqa: E402
from jev_interaction.adapters.openai_compat import OpenAICompatResponder  # noqa: E402
from jev_interaction.latency import TimedSynthesizer, latency_scope  # noqa: E402
from jev_interaction.server import paths  # noqa: E402
from jev_interaction.server.latency_config import snapshot  # noqa: E402
from tools.compare_voice_latency import make_tts  # noqa: E402
from tools.latency_report import distribution  # noqa: E402
from tools.probe_voice_latency import Metrics, failure  # noqa: E402


async def sample(llm, tts, timeout):
    rec, chunks, audio_bytes = Metrics(), 0, 0

    async def text():
        nonlocal chunks
        with latency_scope(rec):
            async with closing_stream(llm.lines([{"role": "user", "content": "请用一句简短中文打个招呼，直接回答。"}], max_tokens=64)) as stream:
                async for _ in stream:
                    chunks += 1

    async def audio():
        nonlocal audio_bytes
        async with closing_stream(TimedSynthesizer(tts, rec, "probe", None).audio("你好，我们开始吧。")) as stream:
            async for chunk in stream:
                audio_bytes += len(chunk)

    result = {}
    for component, consume in (("llm", text), ("tts", audio)):
        started = time.perf_counter()
        try:
            await asyncio.wait_for(consume(), timeout)
            result[component] = {"ok": chunks > 0 if component == "llm" else audio_bytes > 0}
        except Exception as exc:  # noqa: BLE001 - bounded diagnostics only
            result[component] = failure(exc)
        result[component]["elapsed_ms"] = round(1000 * (time.perf_counter() - started), 1)
    return {"components": result, "stages": rec.rows}


def summarize(trials):
    result = {}
    for mode, rows in (("first", trials[:1]), ("later", trials[1:])):
        metrics = {}
        for stage, field in (("llm_first_token", "request_to_first_token_ms"), ("llm_first_chunk", "request_to_first_chunk_ms"),
                             ("tts_first_audio", "request_to_first_audio_ms")):
            component = "tts" if stage.startswith("tts") else "llm"
            values = [s[field] for t in rows if t["components"][component].get("ok") for s in t["stages"]
                      if s.get("stage") == stage and field in s]
            metrics[field] = distribution(values) if values else {"n": 0}
        result[mode] = {"trials": len(rows), "successful": {c: sum(bool(t["components"][c].get("ok")) for t in rows)
                                                          for c in ("llm", "tts")}, "metrics": metrics}
    return result


async def run(args):
    paths.load_env()
    llm = tts = None
    trials, failures, cleanup_errors = [], {"llm": 0, "tts": 0}, []
    try:
        llm, tts = OpenAICompatResponder(), make_tts()
        for index in range(args.trials):
            trial = await sample(llm, tts, args.timeout)
            trials.append({"trial": index + 1, **trial})
            for component, value in trial["components"].items():
                failures[component] = 0 if value.get("ok") else failures[component] + 1
            print(f"Completed {index + 1}/{args.trials}", file=sys.stderr, flush=True)
            if max(failures.values()) >= 3:
                break
    finally:
        for adapter in (tts, llm):
            close = getattr(adapter, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception as exc:  # noqa: BLE001 - still close the other adapter; never retain exception text
                    cleanup_errors.append({"error_type": type(exc).__name__})
    return {"kind": "sequential LLM/TTS components, NOT a cascaded reply or device playback measurement",
            "date": time.strftime("%Y-%m-%d"), "configuration": snapshot(), "timeout_s": args.timeout,
            "stopped_early": max(failures.values()) >= 3, "consecutive_failures": failures,
            "cleanup_errors": cleanup_errors, "summary": summarize(trials), "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.live or not 1 <= args.trials <= 30 or not 0 < args.timeout <= 60:
        parser.error("requires --live, --trials 1..30, --timeout > 0 and <= 60")
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
