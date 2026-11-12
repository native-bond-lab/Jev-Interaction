"""Re-ask Jev the decisions recorded in call logs, as they were asked or with a candidate wording, and show what changes.

    jev-interaction replay runs/*.jsonl --purpose floor            # same questions: how stable are the answers?
    jev-interaction replay runs/*.jsonl --purpose turn --edit my_questions.py

Every "judge" entry in a log holds the state Jev read and the questions it was asked, so a replay sends exactly those.
`--edit` names a Python file defining `edit(purpose, questions) -> questions`; it receives the recorded questions and
returns the candidate. `--purpose` is a decision's name (jev_interaction/decisions). Without labels this shows flips,
not accuracy: read them.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import pathlib
from collections.abc import Callable, Iterable

from .judge import JevClient
from .judge import questions as Q

Edit = Callable[[str, dict], dict]


def rebuild(purpose: str, answers: dict, state: str) -> dict:
    """For logs written before the questions were recorded: today's wording of the built-in questions, guessed from the
    choices that were answered and from the name and pace in the state text."""
    name = state.split("between the user and ", 1)[1].split(".", 1)[0]
    pace = state.split("Current pace of the call: ", 1)[1].split(".", 1)[0]
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


def records(paths: Iterable[str | pathlib.Path], purpose: str) -> Iterable[dict]:
    """The recorded judgements of one decision, in the order they happened."""
    for path in paths:
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("event") == "judge" and r.get("purpose") == purpose:
                yield r


async def replay(judge, entries: Iterable[dict], edit: Edit | None = None, out: Callable[[str], None] = print) -> tuple[int, int]:
    """Re-ask each recorded judgement; (answers compared, answers whose top choice changed)."""
    flips = n = 0
    for r in entries:
        state, purpose = r["state"], r["purpose"]
        qs = r.get("questions") or rebuild(purpose, r["answers"], state)
        if edit:
            qs = edit(purpose, qs)
        new = await judge.ask(qs, state)
        for key, old in r["answers"].items():
            if key not in new or not old:
                continue
            o, w = max(old, key=old.get), new[key]["choice"]
            n += 1
            if o != w:
                flips += 1
                out(f"FLIP {key}: {o} -> {w} | {state.splitlines()[-1][:120]}")
    return n, flips


def load_edit(path: str) -> Edit:
    spec = importlib.util.spec_from_file_location("edit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.edit


def add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("logs", nargs="+", help="call logs (runs/*.jsonl)")
    ap.add_argument("--purpose", default="floor", help="a decision's name: turn, listen, floor, cut_in, quiet, ...")
    ap.add_argument("--edit", default="", help="a Python file defining edit(purpose, questions) -> questions")


async def run(a: argparse.Namespace) -> int:
    judge = JevClient()
    try:
        n, flips = await replay(judge, records(a.logs, a.purpose), load_edit(a.edit) if a.edit else None)
    finally:
        await judge.aclose()
    print(f"{n} answers, {flips} flips")
    return 0


if __name__ == "__main__":
    _ap = argparse.ArgumentParser(prog="python -m jev_interaction.replay")
    add_arguments(_ap)
    raise SystemExit(asyncio.run(run(_ap.parse_args())))
