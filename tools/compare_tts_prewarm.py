"""Randomized first-TTS cold vs prewarmed pairs, with fresh pools in BOTH arms.

    python tools/compare_tts_prewarm.py --live --trials 3 --output experiments/tts-prewarm.json

Uses existing local settings; two short billed syntheses per pair, plus one metadata GET. Never saves audio,
text, credentials, proxy URLs or provider bodies. By default waits for warmup completion, reporting that time
separately: this measures the opportunity when call setup/user speech can cover it, NOT an end-to-end gain.
Use --lead-ms 2000 to give BOTH arms exactly the same 2-second setup opportunity instead. A warmup still in
flight at speech time is cancelled by production code. Proxy jitter remains; a few pairs establish mechanism,
not reliable percentiles. Three consecutive failed syntheses stop the experiment early.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import sys
import time
from unittest.mock import patch

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS  # noqa: E402
from jev_interaction.server import paths  # noqa: E402
from tools.compare_voice_latency import (  # noqa: E402
    _NETWORK,
    make_tts,
    measure_tts,
    paired_summary,
    request_hook,
    response_hook,
)
from tools.latency_report import distribution  # noqa: E402


async def arm(mode, timeout, lead_ms=None):
    synth = make_tts()
    if not isinstance(synth, ElevenLabsTTS):
        close = getattr(synth, "aclose", None)
        if close is not None:
            await close()
        raise ValueError("this prewarm comparison supports ElevenLabs only")
    synth.prewarm = synth.reuse_connection = True
    started = time.perf_counter()
    network = {"started": started, "phases": [], "responses": []}
    token = _NETWORK.set(network)
    warm = None
    try:
        if mode == "prewarm":
            warm = synth.start_warmup()
        if lead_ms is not None:
            await asyncio.sleep(lead_ms / 1000)
        elif warm is not None:
            await warm
        setup_ms = 1000 * (time.perf_counter() - started)
        completed_at_speech = warm.done() and not warm.cancelled() if warm is not None else None
        # measure_tts uses a separate trace context, so warmup and formal synthesis phases remain distinguishable.
        speech = await measure_tts(timeout, synth)
        first = speech.get("comparison", {}).get("direct_first_audio_ms")
        warm_result = None
        if warm is not None:
            await asyncio.gather(warm, return_exceptions=True)
            warm_result = {"ok": False, "outcome": "cancelled"} if warm.cancelled() else warm.result()
        return {"mode": mode, "setup_ms": round(setup_ms, 3), "warmup_completed_at_speech": completed_at_speech,
                "warmup": warm_result, "setup_to_first_audio_ms": round(setup_ms + first, 3) if first is not None else None,
                "warmup_network": {"phases": network["phases"], "responses": network["responses"],
                                   "tcp_connections_started": sum(row["phase"].endswith("connect_tcp.started")
                                                                  for row in network["phases"])},
                "speech": speech}
    finally:
        await synth.aclose()
        _NETWORK.reset(token)


def summarize(trials):
    groups, pairs = {}, []
    for mode in ("cold", "prewarm"):
        samples = [trial["samples"][mode] for trial in trials if mode in trial["samples"]]
        passed = [sample for sample in samples if sample["speech"].get("ok")]
        firsts = [sample["speech"]["comparison"]["direct_first_audio_ms"] for sample in passed]
        totals = [sample["setup_to_first_audio_ms"] for sample in passed]
        groups[mode] = {"calls": len(samples), "successful": len(passed), "failed": len(samples) - len(passed),
                        "first_audio_ms": distribution(firsts) if firsts else {"n": 0},
                        "setup_to_first_audio_ms": distribution(totals) if totals else {"n": 0},
                        "formal_calls_without_new_tcp": sum(s["speech"]["network"]["tcp_connections_started"] == 0 for s in passed),
                        "completed_ok_warmups": sum(bool(s.get("warmup_completed_at_speech")) and
                                                    bool((s.get("warmup") or {}).get("ok")) for s in samples)}
    for trial in trials:
        cold, warm = (trial["samples"].get(mode) for mode in ("cold", "prewarm"))
        if cold and warm and cold["speech"].get("ok") and warm["speech"].get("ok"):
            pairs.append(cold["speech"]["comparison"]["direct_first_audio_ms"] -
                         warm["speech"]["comparison"]["direct_first_audio_ms"])
    return {"groups": groups, "cold_minus_prewarm_first_audio_ms": paired_summary(pairs),
            "caution": "Component requests only. Setup/warmup time is reported, not eliminated. Proxy/provider jitter remains;"
                       " paired samples include unsuccessful warmups and reuse fallbacks. No device playback measurement."}


async def run(args):
    paths.load_env()
    client_type, trials, failures = httpx.AsyncClient, [], 0
    rng = random.Random(args.seed)

    def client(**kwargs):
        kwargs["event_hooks"] = {"request": [request_hook], "response": [response_hook]}
        return client_type(**kwargs)

    with patch.object(httpx, "AsyncClient", client):
        for index in range(args.trials):
            order, samples = ["cold", "prewarm"], {}
            rng.shuffle(order)
            for mode in order:
                samples[mode] = await arm(mode, args.timeout, args.lead_ms)
                failures = 0 if samples[mode]["speech"].get("ok") else failures + 1
                print(f"Pair {index + 1}/{args.trials}: {mode} complete", file=sys.stderr, flush=True)
                if failures >= 3:
                    break
            trials.append({"trial": index + 1, "order": list(samples), "samples": samples})
            if failures >= 3:
                break
    return {"kind": "first-TTS prewarm randomized pairs; NOT microphone-to-speaker latency",
            "date": time.strftime("%Y-%m-%d"), "seed": args.seed, "timeout_s": args.timeout,
            "lead_ms": args.lead_ms, "policy": "fixed setup opportunity" if args.lead_ms is not None else "wait for warmup completion",
            "stopped_early": failures >= 3, "summary": summarize(trials), "trials": trials}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--lead-ms", type=float)
    parser.add_argument("--seed", type=int, default=1731)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.live or not 1 <= args.trials <= 10 or not 0 < args.timeout <= 60:
        parser.error("requires --live, --trials 1..10, and --timeout > 0 and <= 60")
    if args.lead_ms is not None and not 0 <= args.lead_ms <= 10000:
        parser.error("--lead-ms must be 0..10000")
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
