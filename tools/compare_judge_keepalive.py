"""Fixed-input Jev idle-connection A/B, excluding Grok/ASR/TTS and never changing local settings.

Two priming requests plus two requests per pair. Each pair follows an equal idle opportunity.
Only sanitized timings, input hashes and TCP/TLS phase names are saved. Not chat output latency.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import pathlib
import random
import sys
import time
from unittest.mock import patch

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.judge import JevClient, questions  # noqa: E402
from jev_interaction.server import paths  # noqa: E402
from tools.compare_voice_latency import _NETWORK, paired_summary, request_hook, response_hook  # noqa: E402
from tools.latency_report import distribution  # noqa: E402
from tools.probe_voice_latency import failure  # noqa: E402

QUESTIONS = {"done": questions.turn("Agent", "patient", {"patient": "The user speaks; Agent listens."})["done"]}
STATE = ('Phone call between the user and Agent. Agent answers brief questions.\n'
         'Agent is silent. The user said: "What is two plus three?"\n'
         'The user has been quiet for 0.5 s.')


async def measure(client, timeout):
    started = time.perf_counter()
    network = {"started": started, "phases": [], "responses": []}
    token = _NETWORK.set(network)
    try:
        answers = await asyncio.wait_for(client.ask(QUESTIONS, STATE), timeout)
        result = {"ok": set(answers) == set(QUESTIONS)}
    except Exception as exc:  # noqa: BLE001 - never persist provider bodies, headers or arbitrary exception text
        result = failure(exc)
    finally:
        _NETWORK.reset(token)
    return {**result, "elapsed_ms": round(1000 * (time.perf_counter() - started), 3),
            "network": {"phases": network["phases"], "responses": network["responses"],
                        "tcp_connections_started": sum(row["phase"].endswith("connect_tcp.started")
                                                       for row in network["phases"])}}


def summarize(pairs):
    groups, differences = {}, []
    for mode in ("original_5s", "retained_60s"):
        samples = [pair["samples"][mode] for pair in pairs if mode in pair["samples"]]
        passed = [sample for sample in samples if sample["ok"]]
        groups[mode] = {
            "calls": len(samples), "successful": len(passed),
            "elapsed_ms": distribution([sample["elapsed_ms"] for sample in passed]) if passed else {"n": 0},
            "successful_without_new_tcp": sum(s["network"]["tcp_connections_started"] == 0 for s in passed),
        }
    for pair in pairs:
        a, b = (pair["samples"].get(mode) for mode in ("original_5s", "retained_60s"))
        if a and b and a["ok"] and b["ok"]:
            differences.append(a["elapsed_ms"] - b["elapsed_ms"])
    return {"groups": groups, "original_minus_retained_ms": paired_summary(differences),
            "paired_values_ms": [round(value, 3) for value in differences]}


async def run(args):
    paths.load_env()
    client_type = httpx.AsyncClient

    def traced_client(**kwargs):
        kwargs["event_hooks"] = {"request": [request_hook], "response": [response_hook]}
        return client_type(**kwargs)

    rng = random.Random(args.seed)
    report = {"kind": "Fixed synthetic question/state Jev transport comparison; NOT voice/chat latency",
              "date": "2026-11-17", "idle_s": args.idle_s, "seed": args.seed,
              "pool_limits": {"max_connections": 100, "max_keepalive_connections": 20},
              "input_sha256": hashlib.sha256(json.dumps([QUESTIONS, STATE], sort_keys=True).encode()).hexdigest(),
              "policy": "Identical model, timeout, request body and pool capacity; only idle expiry differs.",
              "priming": {}, "pairs": [], "stopped_early": False,
              "caution": "Includes provider processing/network variance; observed TCP reuse is the mechanism check."}
    failures = 0
    with patch.object(httpx, "AsyncClient", traced_client):
        clients = {"original_5s": JevClient(keepalive_expiry=5), "retained_60s": JevClient()}
        try:
            for mode, client in clients.items():
                report["priming"][mode] = await measure(client, args.timeout)
            for index in range(args.trials):
                await asyncio.sleep(args.idle_s)
                order, samples = list(clients), {}
                rng.shuffle(order)
                for mode in order:
                    samples[mode] = await measure(clients[mode], args.timeout)
                    failures = 0 if samples[mode]["ok"] else failures + 1
                    if failures >= 3:
                        report["stopped_early"] = True
                        break
                report["pairs"].append({"pair": index + 1, "order": list(samples), "samples": samples})
                report["summary"] = summarize(report["pairs"])
                args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(f"Jev idle pair {index + 1}/{args.trials} complete", file=sys.stderr, flush=True)
                if report["stopped_early"]:
                    break
        finally:
            for client in clients.values():
                await client.aclose()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--trials", type=int, default=6)
    parser.add_argument("--idle-s", type=float, default=6)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--seed", type=int, default=1731)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not args.live or not 1 <= args.trials <= 12 or not 5 < args.idle_s <= 15 or not 0 < args.timeout <= 30:
        parser.error("requires --live, trials 1..12, idle >5..15 s and timeout >0..30 s")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(run(args))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
