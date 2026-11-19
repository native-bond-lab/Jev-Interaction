"""The user is talking and the agent holds the floor: talk over them now?

Asked only in a pace that allows it (Pace.cut_in), once the user has been talking for a second and a half.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge.client import probs as P
from .base import Decision


class CutIn(Decision):
    name = "cut_in"
    policy = "cut_in"

    def on_words(self, s):
        if not s.speaking and not s.generating and s.params().cut_in:
            s._spawn(self.ask(s, gen=s.gen))

    def ready(self, s, ctx):
        return s.utt is not None and s.utt.speech_ms >= 1500

    def questions(self, s, ctx):
        return {"cut": Q.cut_in(s.p.short)}

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating

    async def apply(self, s, answers, ctx):
        p = P(answers, "cut").get("cut_in", 0.0)
        go = self.policy_for(s, ctx).draw(p)
        s.ledger.note("decision", what="cut_in", p=round(p, 3), go=go)
        if go:
            await s.respond("cut_in")


CUT_IN = CutIn()
