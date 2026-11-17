"""Summarize call latency without printing transcripts, keys or judge states.

    python tools/latency_report.py "runs/call-*.jsonl"
    python tools/latency_report.py "runs/call-*.jsonl" --output experiments/latency_20261117/report.json

Works with legacy logs as well. Server playback ACK metrics include the return network trip; only compare like
networks. Missing stages stay missing, never zero. Error/cancellation counters accompany successful observations.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib
import statistics
from collections import Counter, defaultdict

STAGES = {
    "asr_final": ("last_voice_to_asr_final_ms",),
    "llm_first_token": ("request_to_first_token_ms",),
    "llm_first_chunk": ("request_to_first_chunk_ms", "first_token_to_first_chunk_ms"),
    "line_sent": ("voice_to_line_ms", "asr_to_line_ms"),
    "tts_request": ("line_to_tts_request_ms",),
    "tts_prewarm": ("elapsed_ms",),
    "tts_first_audio": ("request_to_first_audio_ms", "line_to_first_audio_ms"),
    "playback_start": ("voice_to_playback_ack_ms", "asr_to_playback_ack_ms", "response_to_playback_ack_ms",
                       "line_to_playback_ack_ms", "client_receive_to_play_ms"),
}


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"n": len(ordered), "min_ms": round(ordered[0], 1), "p50_ms": round(statistics.median(ordered), 1),
            "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 1), "max_ms": round(ordered[-1], 1)}


def summarize(paths) -> dict:
    samples, counts, kinds = defaultdict(list), Counter(), Counter()
    configs = Counter()
    for path in paths:
        pending = {}
        with pathlib.Path(path).open(encoding="utf-8-sig") as source:
            for raw in source:
                if not raw.strip():
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    counts["malformed_rows"] += 1
                    continue
                if not isinstance(row, dict):
                    counts["malformed_rows"] += 1
                    continue
                event = row.get("event")
                if event == "latency_config":
                    # Only known safe fields, even if a log contains extra data supplied by a third-party recorder.
                    config = {key: row[key] for key in ("schema", "llm_host", "llm_model", "asr", "tts", "chunk_mode",
                              "asr_model", "tts_model", "tts_chunk_bytes", "llm_reuse", "tts_prefetch", "tts_reuse",
                              "tts_prewarm", "preset", "judge_host", "judge_model") if key in row}
                    configs[json.dumps(config, sort_keys=True)] += 1
                elif event == "respond":
                    counts["responses"] += 1
                    kinds[row.get("kind", "unknown")] += 1
                    pending[row["gen"]] = row["t"]
                elif event == "send" and row.get("type") == "line" and row.get("gen") in pending:
                    samples["respond_to_first_line_ms"].append(1000 * (row["t"] - pending.pop(row["gen"])))
                    counts["responses_with_line"] += 1
                elif event == "judge":
                    samples[f"judge_{row['purpose']}_ms"].append(row["ms"])
                elif event in ("no_reply", "judge_error", "tick_error", "task_error"):
                    counts[event] += 1
                elif event == "send" and row.get("type") == "error":
                    counts[f"client_error_{row.get('what', 'unknown')}"] += 1
                elif event == "latency":
                    stage = row.get("stage")
                    counts[f"stage_{stage}"] += 1
                    if stage == "line_sent" and row.get("first") is True:
                        counts["traced_responses_with_line"] += 1
                    if stage == "playback_start" and row.get("first") is True:
                        counts["responses_with_playback_ack"] += 1
                    if stage == "llm_end":
                        counts[f"llm_{row.get('status', 'unknown')}"] += 1
                    if stage == "tts_end" and not row.get("complete"):
                        counts["tts_incomplete"] += 1
                    if stage == "tts_prewarm":
                        counts[f"tts_prewarm_{row.get('outcome', 'unknown')}"] += 1
                        counts["tts_prewarm_ok" if row.get("ok") else "tts_prewarm_not_ok"] += 1
                    if stage in ("line_sent", "playback_start") and row.get("first") is not True:
                        continue
                    for field in STAGES.get(stage, ()):
                        value = row.get(field)
                        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                            samples[field].append(value)
        counts["responses_without_line"] += len(pending)
    return {"files": len(paths), "counts": dict(counts), "response_kinds": dict(kinds),
            "configurations": [{"calls": n, **json.loads(config)} for config, n in configs.items()],
            "mixed_configurations": len(configs) > 1,
            "metrics": {name: distribution(values) for name, values in sorted(samples.items()) if values},
            "notes": ["Percentiles use nearest rank. Small samples are descriptive, not proof of improvement.",
                      "Playback ACK includes the return network trip. Voice time is server VAD frame arrival, not microphone end time.",
                      "LLM and TTS request metrics include all observed attempts; first-line/playback metrics are per reply.",
                      "Missing stages are not estimated. Errors and responses without audio need separate review."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", help="JSONL paths or quoted globs")
    parser.add_argument("--output", type=pathlib.Path, help="write the full report as JSON")
    args = parser.parse_args()
    paths = sorted({path for pattern in args.logs for path in glob.glob(pattern) if pathlib.Path(path).is_file()})
    if not paths:
        parser.error("no log files matched")
    report = summarize(paths)
    print(f"Files: {len(paths)} | counts: {json.dumps(report['counts'], ensure_ascii=False)}")
    if report["mixed_configurations"]:
        print("Multiple configurations detected. Overall metrics combine them; select one stack's log files for comparison.")
    print(f"{'metric':42s} {'n':>5s} {'P50 ms':>10s} {'P95 ms':>10s} {'max ms':>10s}")
    for name, row in report["metrics"].items():
        print(f"{name:42s} {row['n']:5d} {row['p50_ms']:10.1f} {row['p95_ms']:10.1f} {row['max_ms']:10.1f}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
