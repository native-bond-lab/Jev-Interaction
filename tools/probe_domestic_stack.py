"""Run bounded, real provider probes with private settings; emit metrics and status codes only."""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.local_voice_profile import PROFILE, ROOT, activate  # noqa: E402


def failure(exc):
    # Never stringify arbitrary exceptions, response bodies, request URLs or headers into output.
    import httpx
    result = {"ok": False, "error_type": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        result["http_status"] = exc.response.status_code
    response = getattr(exc, "response", None)
    if response is not None and hasattr(response, "status_code"):
        result["http_status"] = response.status_code
    match = re.fullmatch(r"(?:Doubao (?:TTS|ASR) error code |jev )(\d+)(?::.*)?", str(exc), re.S)
    if match:
        result["provider_code"] = int(match[1])
    return result


async def judge_probe():
    from jev_interaction.judge.client import JevClient
    from jev_interaction.judge.questions import turn
    from jev_interaction.profile import Profile
    from jev_interaction.server import paths
    profile = Profile.load(paths.profiles()["support_zh"])
    client, started = JevClient(), time.monotonic()
    questions = turn(profile.short, "service", {"service": "Brief support, let the caller finish."})
    try:
        answer = await asyncio.wait_for(client.ask(questions, "The caller has finished asking: please say hello in Chinese."), 20)
        valid = all(isinstance(answer.get(name, {}).get("probabilities"), dict)
                    and set(answer[name]["probabilities"]) == set(question["criteria"])
                    for name, question in questions.items())
        return {"ok": valid, "question_count": len(questions), "elapsed_ms": round(1000 * (time.monotonic() - started), 1)}
    finally:
        await client.aclose()


async def asr_probe():
    from jev_interaction.adapters.doubao_asr import DoubaoRealtime
    asr, started = DoubaoRealtime(language="zh"), time.monotonic()
    try:
        await asyncio.wait_for(asr.connect(), 15)
        await asr.send(b"\x00" * 6400)
        return {"ok": True, "setup_ack_ms": round(1000 * (time.monotonic() - started), 1),
                "scope": "authenticated setup and PCM send; recognition still requires speech roundtrip"}
    finally:
        await asr.close()


async def run(args):
    activate(args.profile)
    from jev_interaction.server import paths
    from jev_interaction.server.latency_config import snapshot
    from tools.probe_voice_latency import llm_probe, tts_probe
    paths.load_env()
    report = {"kind": "real direct-network component probes, not full voice-chat latency", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "configuration": snapshot(), "results": {}}
    for name, probe in (("judge", judge_probe), ("llm", lambda: llm_probe(30)),
                        ("tts", lambda: tts_probe(25)), ("asr", asr_probe)):
        if args.only and name not in args.only:
            continue
        try:
            report["results"][name] = await probe()
        except Exception as exc:
            report["results"][name] = failure(exc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"node": name, **report["results"][name]}, ensure_ascii=True), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=pathlib.Path, default=PROFILE)
    parser.add_argument("--only", nargs="+", choices=("judge", "llm", "asr", "tts"))
    parser.add_argument("--output", type=pathlib.Path,
                        default=ROOT / "experiments/latency_20261117/domestic-stack/components.json")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    return 0 if all(r["ok"] for r in report["results"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
