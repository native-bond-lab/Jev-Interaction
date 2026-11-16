"""The user is talking and the agent holds the floor: talk over them now?

Asked only in a pace that allows it (Pace.cut_in), once the user has been talking for a second and a half.
"""
from __future__ import annotations

import time

from ..judge import questions as Q
from ..judge import state as S
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

    def state(self, s, ctx):
        return super().state(s, ctx) + S.user_turn(s.p.short, s.utt.segments, time.monotonic(), s.silence_ms, False, s.utt.asides)

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating

    async def apply(self, s, answers, ctx):
        if self.policy_for(s, ctx).draw(P(answers, "cut").get("cut_in", 0.0)):
            await s.respond("cut_in")


CUT_IN = CutIn()
