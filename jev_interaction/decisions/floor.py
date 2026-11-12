"""Both talk at once: carry on, yield, finish the sentence, take the floor back, react, or answer in a word.

Asked on every segment of words heard while the agent is speaking or about to. Which choices are offered depends on the
pace (judge/questions.py: floor_criteria). A judge that fails leaves the agent carrying on, with the hold released.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from ..policy import ThresholdPolicy
from .base import Decision


class Floor(Decision):
    name = "floor"
    policy = "floor"

    def on_words(self, s):
        if s.speaking or s.generating:
            s._spawn(self.ask(s, gen=s.gen))

    def ready(self, s, ctx):
        return s.utt is not None and bool(s.utt.segments)

    def questions(self, s, ctx):
        pace = ctx["pace"] = s.params()
        criteria = Q.floor_criteria(s.p.short, finish=not pace.leads, overrule=pace.cut_in,
                                    aside=pace.leads and not pace.cut_in, jump=True)
        if s._offer_elsewhere():
            criteria["elsewhere"] = Q.elsewhere(s.p.short)
        ctx["criteria"] = criteria
        return {"floor": Q.floor(s.p.short, criteria)}

    def state(self, s, ctx):
        line = s.ledger.last_agent().text if s.ledger.last_agent() else ""
        return super().state(s, ctx) + S.overlap(s.p.short, line, s.utt.text, s.utt.speech_ms)

    def allowed(self, s, ctx):
        return ctx["criteria"]                    # the choices this pace was offered

    def policy_for(self, s, ctx):
        policy = super().policy_for(s, ctx)
        if isinstance(policy, ThresholdPolicy):   # how sure Jev must be before the line stops comes from the (blended) pace
            policy = ThresholdPolicy({**policy.thresholds, "yield": ctx["pace"].yield_p}, policy.default,
                                     policy.fallback or "carry_on")
        return policy

    async def apply(self, s, answers, ctx):
        probs = P(answers, "floor")
        if s._far() or (s._offer_elsewhere() and probs and max(probs, key=probs.get) == "elsewhere"):
            await s.send(type="decision", what="floor", action="carry_on", probs=probs)
            await s._not_for_me("far" if s._far() else "jev")
            return
        action = self.choose(s, answers, "floor", ctx) or "carry_on"
        if action == "elsewhere":                           # drawn but not the likeliest: not enough to treat as an aside
            action = "carry_on"
        await s.send(type="decision", what="floor", action=action, probs=probs)
        if action == "carry_on":
            s.held = False
            await s.send(type="unhold", gen=s.gen)
        elif action == "finish_first":
            s.held = False
            await s.send(type="unhold", gen=s.gen)
            await s.send(type="finish_line", gen=s.gen)     # the queued lines are dropped; their turn comes after
        elif action == "yield":
            await s._stop_line()                            # the utterance goes on and is answered when it ends
        else:                                               # overrule / aside / jump_in: a word now
            await s._stop_line()
            await s.respond(action)


FLOOR = Floor()
