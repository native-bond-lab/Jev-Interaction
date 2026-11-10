"""Re-ask Jev the decisions recorded in call logs, with today's questions or a candidate wording, and show what changes.

    python tools/replay.py runs/*.jsonl --purpose floor            # same questions: how stable are the answers?
    python tools/replay.py runs/*.jsonl --purpose turn --edit my_questions.py

`--edit` names a Python file defining `edit(purpose, questions) -> questions`; it receives the recorded question set
rebuilt from judge/questions.py and returns the candidate. Without labels this shows flips, not accuracy: read them.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jev_interaction.judge import JevClient  # noqa: E402
from jev_interaction.judge import questions as Q  # noqa: E402


def rebuild(purpose: str, answers: dict, name: str, pace: str) -> dict:
    """The question set behind a recorded judgement, from the choices it was answered with."""
    out = {}
    for key, probs in answers.items():
        if key == "floor":
            crit = Q.floor_criteria(name, finish="finish_first" in probs, overrule="overrule" in probs, aside="aside" in probs,
                                    jump="jump_in" in probs)
            out[key] = Q.floor(name, crit)
        elif key == "listen":
            out[key] = Q.listen(name)
        elif key == "cut":
            out[key] = Q.cut_in(name)
        elif key == "quiet":
            out[key] = Q.quiet(name, pace)
    if purpose == "turn":
        out.update({k: v for k, v in Q.turn(name, pace, {k: k for k in answers.get("pace", {})}).items() if k in answers})
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--purpose", default="floor")
    ap.add_argument("--edit", default="")
    a = ap.parse_args()
    edit = None
    if a.edit:
        spec = importlib.util.spec_from_file_location("edit", a.edit)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        edit = mod.edit
    judge = JevClient()
    flips = n = 0
    for path in a.logs:
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") != "judge" or r.get("purpose") != a.purpose:
                continue
            state = r["state"]
            name = state.split("between the user and ", 1)[1].split(".", 1)[0]
            pace = state.split("Current pace of the call: ", 1)[1].split(".", 1)[0]
            qs = rebuild(a.purpose, r["answers"], name, pace)
            if edit:
                qs = edit(a.purpose, qs)
            new = await judge.ask(qs, state)
            for key, old in r["answers"].items():
                if key not in new or not old:
                    continue
                o, w = max(old, key=old.get), new[key]["choice"]
                n += 1
                if o != w:
                    flips += 1
                    print(f"FLIP {key}: {o} -> {w} | {state.splitlines()[-1][:120]}")
    print(f"{n} answers, {flips} flips")
    await judge.aclose()


if __name__ == "__main__":
    asyncio.run(main())
