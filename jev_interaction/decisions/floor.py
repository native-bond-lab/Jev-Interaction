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

STOPS = ("yield", "overrule", "aside", "jump_in")       # every answer that drops the line the agent is on


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

    def split_stop(self, s, probs, action, ctx):
        """Jev is sure the line should stop but split on what comes next ("yield" 0.43, "overrule" 0.48: neither reaches
        its own threshold, and the agent used to talk on over "let me finish!"). When the ways of stopping together
        outweigh going on and reach the pace's yield threshold, the likeliest of them is taken."""
        policy = self.policy_for(s, ctx)
        if action != "carry_on" or not isinstance(policy, ThresholdPolicy):
            return action
        stops = {k: probs.get(k, 0.0) for k in STOPS if k in ctx["criteria"]}
        mass = sum(stops.values())
        if mass >= ctx["pace"].yield_p and mass > probs.get("carry_on", 0.0) + probs.get("finish_first", 0.0):
            return max(stops, key=stops.get)
        return action

    async def apply(self, s, answers, ctx):
        probs = P(answers, "floor")
        if s._far() or (s._offer_elsewhere() and probs and max(probs, key=probs.get) == "elsewhere"):
            await s.send(type="decision", what="floor", action="carry_on", probs=probs)
            await s._not_for_me("far" if s._far() else "jev")
            return
        action = self.choose(s, answers, "floor", ctx) or "carry_on"
        if action == "elsewhere":                           # drawn but not the likeliest: not enough to treat as an aside
            action = "carry_on"
        action = self.split_stop(s, probs, action, ctx)
        await s.send(type="decision", what="floor", action=action, probs=probs)
        if action == "carry_on":
            s.held = False
            await s.send(type="unhold", gen=s.gen)
            if s.speaking:                                  # said over a line that goes on: into the call's record at once
                s.ledger.said_over(s.utt.text)              # (not a turn to answer); the next sound starts from nothing
                s.utt, s.judged = None, None
            else:
                s.utt.over_ms = 0
        elif action == "finish_first":
            s.held = False
            s.utt.over_ms = 0
            await s.send(type="unhold", gen=s.gen)
            await s.send(type="finish_line", gen=s.gen)     # the queued lines are dropped; their turn comes after
        elif action == "yield":
            await s._stop_line()                            # the utterance goes on and is answered when it ends
        else:                                               # overrule / aside / jump_in: a word now
            await s._stop_line()
            await s.respond(action)


FLOOR = Floor()
