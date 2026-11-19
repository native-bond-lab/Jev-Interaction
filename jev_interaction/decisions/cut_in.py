"""The user is talking and the agent holds the floor: talk over them now?

Asked only in a pace that allows it (Pace.cut_in), once the user has been talking for a second and a half. Carried by
the turn question, like listen (turn.py asks them in one request on new words): cutting in, taking the turn and
putting a sound in are one choice there, and one of them happens. `Session.ask_cut_in` still asks it on its own.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge.client import probs as P
from .base import Decision


class CutIn(Decision):
    name = "cut_in"
    policy = "cut_in"

    def ready(self, s, ctx):
        return s.utt is not None and s.utt.speech_ms >= 1500

    def wanted(self, s, ctx) -> bool:
        """Is cutting in open right now: a pace that allows it, and the user has been talking a while."""
        return s.params().cut_in and self.ready(s, ctx)

    def questions(self, s, ctx):
        return {"cut": Q.cut_in(s.p.short)}

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating

    def go(self, s, answers, ctx) -> bool:
        p = P(answers, "cut").get("cut_in", 0.0)
        go = self.policy_for(s, ctx).draw(p)
        s.ledger.note("decision", what="cut_in", p=round(p, 3), go=go)
        return go

    async def apply(self, s, answers, ctx):
        if self.go(s, answers, ctx):
            await s.respond("cut_in")


CUT_IN = CutIn()
