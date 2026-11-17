"""Proxy-tolerant latency experiments: shadow both buffering policies on ONE real stream.

    python tools/compare_voice_latency.py --live --llm --tts --trials 5 --output experiments/voice-comparison.json
    python tools/compare_voice_latency.py --live --llm --connection-ab --trials 20 --output experiments/connection-ab.json

Explicit --live permits billed calls: one LLM/TTS call per selected component per trial; connection A/B doubles LLM
calls. Credentials stay in local settings. No transcript, generated text or audio is saved. Connection A/B is still
affected by proxy/provider variation; interleaving and paired summaries reduce, not remove, that uncertainty.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import pathlib
import random
import re
import statistics
import sys
import time
from collections import Counter
from contextvars import ContextVar
from unittest.mock import patch

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction import speaking  # noqa: E402
from jev_interaction.adapters import openai_compat, registry  # noqa: E402
from jev_interaction.adapters.base import closing_stream  # noqa: E402
from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS  # noqa: E402
from jev_interaction.adapters.speech_chunks import SpeechChunks  # noqa: E402
from jev_interaction.latency import latency_scope  # noqa: E402
from jev_interaction.profile import Profile  # noqa: E402
from jev_interaction.server import paths  # noqa: E402
from jev_interaction.server.latency_config import snapshot  # noqa: E402
from tools.latency_report import distribution  # noqa: E402
from tools.probe_voice_latency import Metrics, failure  # noqa: E402

_NETWORK = ContextVar("voice_experiment_network", default=None)


class ChunkComparison:
    """The production chunker in both modes, fed identical deltas at the same arrival time."""
    def __init__(self, mode):
        if mode not in ("newline", "first_sentence"):
            raise ValueError("unknown chunk mode")
        self.mode = mode
        self.parsers = {name: SpeechChunks(name) for name in ("newline", "first_sentence")}
        self.first = {name: None for name in self.parsers}
        self.hashes = {name: hashlib.sha256() for name in self.parsers}

    def _record(self, outputs, now):
        for name, chunks in outputs.items():
            for chunk in chunks:
                if self.first[name] is None and speaking.has_voice(chunk):
                    self.first[name] = now
                self.hashes[name].update(re.sub(r"\s", "", chunk).encode())
        return outputs[self.mode]

    def feed(self, delta):
        now = time.perf_counter()
        return self._record({name: parser.feed(delta) for name, parser in self.parsers.items()}, now)

    def finish(self):
        now = time.perf_counter()
        return self._record({name: parser.finish() for name, parser in self.parsers.items()}, now)

    def result(self, started, complete):
        first = {name: round(1000 * (at - started), 3) if at is not None else None for name, at in self.first.items()}
        saved = (self.first["newline"] - self.first["first_sentence"]) * 1000 if all(
            at is not None for at in self.first.values()) else None
        return {"first_ready_ms": first, "same_stream_saved_ms": round(saved, 3) if saved is not None else None,
                "same_spoken_text": self.hashes["newline"].digest() == self.hashes["first_sentence"].digest() if complete else None}


class AudioComparison:
    def __init__(self):
        self.first = self.buffered_first = None
        self.first_chunk_bytes = self.bytes = 0
        self.pending = bytearray()
        self.raw_hash, self.buffered_hash = hashlib.sha256(), hashlib.sha256()

    def feed(self, chunk):
        now = time.perf_counter()
        if chunk and self.first is None:
            self.first, self.first_chunk_bytes = now, len(chunk)
        self.bytes += len(chunk)
        self.raw_hash.update(chunk)
        self.pending.extend(chunk)
        while len(self.pending) >= 4096:
            if self.buffered_first is None:
                self.buffered_first = now
            self.buffered_hash.update(self.pending[:4096])
            del self.pending[:4096]

    def finish(self):
        if self.pending:
            if self.buffered_first is None:
                self.buffered_first = time.perf_counter()
            self.buffered_hash.update(self.pending)
            self.pending.clear()

    def result(self, started, complete):
        saved = (self.buffered_first - self.first) * 1000 if self.first is not None and self.buffered_first is not None else None
        return {"direct_first_audio_ms": round(1000 * (self.first - started), 3) if self.first is not None else None,
                "buffered_4096_first_audio_ms": round(1000 * (self.buffered_first - started), 3)
                if self.buffered_first is not None else None,
                "same_stream_saved_ms": round(saved, 3) if saved is not None else None,
                "first_chunk_bytes": self.first_chunk_bytes, "audio_bytes": self.bytes,
                "same_audio_bytes": self.raw_hash.digest() == self.buffered_hash.digest() if complete else None}


async def request_hook(request):
    state = _NETWORK.get()
    if state is None:
        return

    async def trace(name, info):
        # Trace payloads, URLs, headers and credentials are intentionally not retained.
        state["phases"].append({"phase": name, "at_ms": round(1000 * (time.perf_counter() - state["started"]), 3)})

    request.extensions["trace"] = trace


async def response_hook(response):
    state = _NETWORK.get()
    if state is not None:
        state["responses"].append({"http_status": response.status_code,
                                   "headers_at_ms": round(1000 * (time.perf_counter() - state["started"]), 3)})


async def measure_llm(client, timeout):
    rec, comparisons = Metrics(), []
    started = time.perf_counter()
    network = {"started": started, "phases": [], "responses": []}
    token = _NETWORK.set(network)

    def chunker(mode):
        comparison = ChunkComparison(mode)
        comparisons.append(comparison)
        return comparison

    async def consume():
        with patch.object(openai_compat, "SpeechChunks", chunker), latency_scope(rec):
            async with closing_stream(client.lines([
                {"role": "user", "content": "请用两句简短中文说明语音助手能做什么，每句不超过十五个字，直接回答。"}
            ], max_tokens=64)) as stream:
                async for _ in stream:
                    pass

    try:
        await asyncio.wait_for(consume(), timeout)
        complete = any(row.get("stage") == "llm_end" and row.get("status") == "complete" for row in rec.rows)
        comparison = comparisons[-1].result(started, complete) if comparisons else {}
        result = {"ok": complete and all(value is not None for value in comparison.get("first_ready_ms", {}).values()),
                  "comparison": comparison}
    except Exception as exc:  # noqa: BLE001
        result = {**failure(exc), "comparison": comparisons[-1].result(started, False) if comparisons else {}}
    finally:
        _NETWORK.reset(token)
    return {**result, "elapsed_ms": round(1000 * (time.perf_counter() - started), 3), "stages": rec.rows,
            "network": {"phases": network["phases"], "responses": network["responses"],
                        "tcp_connections_started": sum(row["phase"].endswith("connect_tcp.started") for row in network["phases"])}}


def make_tts():
    profile = Profile.load(paths.profiles()["companion"])
    voice = (profile.extra.get("voices") or {}).get(registry.selected("tts"))
    return registry.create("tts", voice=voice)


async def measure_tts(timeout, synth=None):
    comparison, started = AudioComparison(), time.perf_counter()
    owned = synth is None
    network = {"started": started, "phases": [], "responses": []}
    token = _NETWORK.set(network)
    try:
        if synth is None:
            synth = make_tts()
        if not isinstance(synth, ElevenLabsTTS):
            return {"ok": False, "skipped": "4096-byte baseline applies to ElevenLabs only"}
        synth.chunk_bytes = None  # compare both strategies on the unbuffered stream; never writes .env

        async def consume():
            async with closing_stream(synth.audio("你好，我们开始吧。")) as stream:
                async for chunk in stream:
                    comparison.feed(chunk)
            comparison.finish()

        await asyncio.wait_for(consume(), timeout)
        result = {"ok": comparison.bytes > 0, "comparison": comparison.result(started, True)}
    except Exception as exc:  # noqa: BLE001
        result = {**failure(exc), "comparison": comparison.result(started, False)}
    finally:
        _NETWORK.reset(token)
        close = getattr(synth, "aclose", None) if owned else None
        if close is not None:
            await close()
    return {**result, "elapsed_ms": round(1000 * (time.perf_counter() - started), 3),
            "network": {"phases": network["phases"], "responses": network["responses"],
                        "tcp_connections_started": sum(row["phase"].endswith("connect_tcp.started") for row in network["phases"])}}


def paired_summary(values):
    result = {"distribution": distribution(values) if values else {"n": 0}, "median_ci95_ms": None}
    if len(values) >= 10:
        rng = random.Random(1731)
        estimates = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(2000))
        result["median_ci95_ms"] = [round(estimates[49], 3), round(estimates[1949], 3)]
    return result


def summarize(trials):
    result = {}
    for component in ("llm", "tts"):
        samples = [sample for trial in trials for name, sample in trial["samples"].items() if name.startswith(component)]
        if not samples:
            continue
        successful = [sample for sample in samples if sample.get("ok")]
        diffs = [sample["comparison"]["same_stream_saved_ms"] for sample in successful
                 if sample.get("comparison", {}).get("same_stream_saved_ms") is not None]
        result[component] = {"calls": len(samples), "successful": len(successful), "failed_or_skipped": len(samples) - len(successful),
                             "same_stream_saved_ms": paired_summary(diffs)}
    paired, failed = [], 0
    for trial in trials[1:]:  # keep the initial reusable-client request as an explicit cold/warmup pair
        samples = trial["samples"]
        if "llm_reuse" not in samples:
            continue
        reuse, fresh = samples["llm_reuse"], samples["llm_fresh"]
        if reuse.get("ok") and fresh.get("ok"):
            a = fresh["comparison"]["first_ready_ms"]["first_sentence"]
            b = reuse["comparison"]["first_ready_ms"]["first_sentence"]
            paired.append(a - b)
        else:
            failed += 1
    if trials and "llm_reuse" in trials[0]["samples"]:
        groups = {}
        for name in ("llm_reuse", "llm_fresh"):
            samples = [trial["samples"][name] for trial in trials]

            def ready(sample):
                return sample.get("comparison", {}).get("first_ready_ms", {}).get("first_sentence")

            warm_ready = [ready(sample) for sample in samples[1:] if sample.get("ok") and ready(sample) is not None]
            groups[name] = {
                "calls": len(samples), "successful": sum(bool(sample.get("ok")) for sample in samples),
                "failed": sum(not sample.get("ok") for sample in samples),
                "error_types": dict(Counter(sample.get("error_type", "unknown") for sample in samples if not sample.get("ok"))),
                "after_cold_pair_first_ready_ms": distribution(warm_ready) if warm_ready else {"n": 0},
                "successful_calls_without_new_tcp": sum(sample.get("ok") and
                                                        sample.get("network", {}).get("tcp_connections_started") == 0
                                                        for sample in samples),
                "tls_failed_calls": sum(any(row["phase"].endswith("start_tls.failed") for row in
                                            sample.get("network", {}).get("phases", [])) for sample in samples),
            }
        result["connection_strategy"] = {"cold_pair_trial": 1, "failed_pairs_after_warmup": failed,
                                           "groups": groups,
                                           "fresh_minus_reuse_first_sentence_ms": paired_summary(paired),
                                           "caution": "Includes proxy/provider jitter and reuse fallbacks; CI crossing zero is inconclusive."
                                           " Bootstrap CI assumes independent pairs; inspect time drift and repeat in separate sessions."}
    return result


async def run(args):
    paths.load_env()
    trials, rng, clients = [], random.Random(args.seed), []
    failures, stopped_early = Counter(), False
    client_type = httpx.AsyncClient

    def http_client(**kwargs):
        kwargs["event_hooks"] = {"request": [request_hook], "response": [response_hook]}
        return client_type(**kwargs)

    with patch.object(httpx, "AsyncClient", http_client):
        try:
            reused = fresh = None
            reused_tts = None
            if getattr(args, "tts_reuse", False):
                reused_tts = make_tts()
                if not isinstance(reused_tts, ElevenLabsTTS):
                    raise ValueError("--tts-reuse is only supported for ElevenLabs")
                reused_tts.reuse_connection = True
                clients.append(reused_tts)
            if args.llm:
                reused = openai_compat.OpenAICompatResponder(temperature=0)
                reused.chunk_mode, reused.reuse_connection = "first_sentence", True
                clients.append(reused)
                if args.connection_ab:
                    fresh = openai_compat.OpenAICompatResponder(temperature=0)
                    fresh.chunk_mode, fresh.reuse_connection = "first_sentence", False
                    clients.append(fresh)
            for index in range(args.trials):
                samples, order = {}, []
                modes = ["llm_reuse", "llm_fresh"] if args.connection_ab else (["llm"] if args.llm else [])
                rng.shuffle(modes)
                for mode in modes:
                    order.append(mode)
                    samples[mode] = await measure_llm(fresh if mode == "llm_fresh" else reused, args.timeout)
                if args.tts:
                    order.append("tts")
                    samples["tts"] = await measure_tts(args.timeout, reused_tts)
                trials.append({"trial": index + 1, "order": order, "samples": samples})
                for mode, sample in samples.items():
                    failures[mode] = 0 if sample.get("ok") else failures[mode] + 1
                print(f"Completed trial {index + 1}/{args.trials}", file=sys.stderr, flush=True)
                if any(count >= 3 for count in failures.values()):
                    stopped_early = True
                    break
        finally:
            for client in clients:
                await client.aclose()
    return {"kind": "same-stream buffering comparison; optional randomized paired connection A/B; NOT device output latency",
            "date": time.strftime("%Y-%m-%d"), "seed": args.seed, "timeout_s": args.timeout,
            "configuration": snapshot(), "stopped_early": stopped_early, "consecutive_failures": dict(failures),
            "tts_connection_mode": "shared client across trials" if getattr(args, "tts_reuse", False) else "one synthesizer per trial",
            "summary": summarize(trials), "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--tts", action="store_true")
    parser.add_argument("--tts-reuse", action="store_true", help="reuse one ElevenLabs TTS pool across trials; a warm-connection probe, not an A/B")
    parser.add_argument("--connection-ab", action="store_true")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--seed", type=int, default=1731)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.live or not (args.llm or args.tts):
        parser.error("select --live and at least one of --llm / --tts")
    if args.connection_ab and (not args.llm or args.trials < 2):
        parser.error("--connection-ab needs --llm and at least 2 trials (the first pair is cold/warmup)")
    if args.tts_reuse and not args.tts:
        parser.error("--tts-reuse needs --tts")
    if not 1 <= args.trials <= 100 or not 0 < args.timeout <= 60:
        parser.error("--trials must be 1..100; --timeout must be > 0 and <= 60")
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
