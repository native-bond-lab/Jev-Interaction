"""The user is talking and the agent holds the floor: talk over them now?

Jev is asked a fact about the user's words, not what the agent should do: are they sparring (teasing, taunting,
daring, going round in circles) or telling something that has to be heard out. The agent cuts in when Jev is sure
enough of the first (the policy under "cut_in", a threshold by default).

Asked only in a pace that allows it (Pace.cut_in), once the user has been talking for a second and a half. Carried by
the turn question, like listen (turn.py asks them in one request on new words): cutting in, taking the turn and
putting a sound in are one choice there, and one of them happens. `Session.ask_cut_in` still asks it on its own.
"""
from __future__ import annotations

from ..judge import bailian as B
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
        return B.both("spar", Q.sparring())           # in both option orders, like every small fact

    def state(self, s, ctx):
        return self.pointed(super().state(s, ctx), s)

    @staticmethod
    def pointed(state: str | dict, s) -> dict:
        """The state with the words the question points at in a field of their own."""
        state = dict(state) if isinstance(state, dict) else {"call": state}
        return {**state, "user_words_so_far": s.utt.heard if s.utt else ""}

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating

    def go(self, s, answers, ctx) -> bool:
        p = P(answers, "spar").get("sparring", 0.0)
        go = self.policy_for(s, ctx).draw(p)
        s.ledger.note("decision", what="cut_in", p=round(p, 3), go=go)
        return go

    async def apply(self, s, answers, ctx):
        if self.go(s, answers, ctx):
            await s.respond("cut_in")


CUT_IN = CutIn()
