"""Both talk at once: carry on, yield, finish the sentence, take the floor back, react, or answer in a word.

Asked on every segment of words heard while the agent is speaking or about to, and earlier, on the words so far, once
the user's voice has been over the line for Config.overlap_ask_ms (`Session._over`): asked early, only "the user needs
the floor" does anything (the line stops); every other answer waits for the words to close. No clock touches the line:
it plays until Jev says stop. Which choices are offered depends on the pace (judge/questions.py: floor_criteria). A
judge that fails leaves the agent carrying on.
"""
from __future__ import annotations

import os

from ..judge import bailian as B
from ..judge import questions as Q
from ..judge.client import probs as P
from ..policy import ThresholdPolicy
from .base import Decision

STOPS = ("yield", "overrule", "aside", "jump_in")       # every answer that drops the line the agent is on
MAY_TAKE = ("yield", "finish_first", "jump_in")         # what a deployment may set JEV_FLOOR_FALLBACK to


def no_answer() -> str:
    """What to do when the judge gave no answer at all (it failed): carry on, as documented — unless the deployment
    said otherwise (`JEV_FLOOR_FALLBACK=yield`). Without a judge nothing else can stop a line, so a call on a judge
    that is down is otherwise impossible to talk over."""
    said = (os.getenv("JEV_FLOOR_FALLBACK") or "").strip().lower()
    return said if said in MAY_TAKE else "carry_on"


class Floor(Decision):
    name = "floor"
    policy = "floor"

    def on_words(self, s):
        if s.speaking or s.generating:
            s._spawn(self.ask(s, gen=s.gen))

    async def ask(self, s, **ctx):
        await super().ask(s, **ctx)
        if (ctx.get("early") and s.utt is not None and len(s.utt.segments) > ctx.get("closed", 0)
                and (s.speaking or s.generating)):
            await super().ask(s, gen=s.gen)       # the words closed while Jev was reading them unclosed: asked as they stand

    def ready(self, s, ctx):
        """The words make out what they said; without them, the voice over the line is enough to ask what to do about it."""
        return s.utt is not None and (bool(s.utt.heard) or s.utt.over_ms >= s.cfg.overlap_ask_ms)

    def questions(self, s, ctx):
        pace = ctx["pace"] = s.params()
        criteria = Q.floor_criteria(s.p.short, finish=not pace.leads, overrule=pace.cut_in,
                                    aside=pace.leads and not pace.cut_in, jump=True)
        if s._offer_elsewhere():
            criteria["elsewhere"] = Q.elsewhere(s.p.short)
        if s.cfg.judge_provider == "bailian":
            questions = B.floor(criteria)
            ctx["criteria"] = questions["floor"]["criteria"]
            return questions
        ctx["criteria"] = criteria
        return {"floor": Q.floor(s.p.short, criteria)}

    def state(self, s, ctx):
        text, m = super().state(s, ctx), ctx["now"]
        heard = m.heard or "(they have started talking over you, but no words have been recognized yet)"
        return B.floor_state(text, m.agent_line, heard) if s.cfg.judge_provider == "bailian" else text

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

    def decided(self, s, answers, probs, ctx) -> str:
        """The policy's choice; and, when the judge answered nothing at all, what the deployment says instead."""
        action = self.choose(s, answers, "floor", ctx) or "carry_on"
        return no_answer() if not probs and action == "carry_on" else action

    async def apply(self, s, answers, ctx):
        probs = P(answers, "floor")
        elsewhere = bool(s._someone_else()) or (s._offer_elsewhere() and probs and max(probs, key=probs.get) == "elsewhere")
        if ctx.get("early"):                                # on words not closed yet: only a user who needs the floor
            action = None if elsewhere else self.split_stop(s, probs, self.decided(s, answers, probs, ctx), ctx)
            if action == "yield":                           # stops the line now; the rest is decided when the words close
                if s._called_floor_protected():
                    await s.send(type="decision", what="floor", action="carry_on", early=True,
                                 probs=probs, shielded=True)
                    return
                await s.send(type="decision", what="floor", action=action, early=True, probs=probs)
                await s._stop_line()
            return
        if elsewhere:
            await s.send(type="decision", what="floor", action="carry_on", probs=probs)
            await s._not_for_me(s._someone_else() or "jev")
            return
        action = self.decided(s, answers, probs, ctx)
        if action == "elsewhere":                           # drawn but not the likeliest: not enough to treat as an aside
            action = "carry_on"
        action = self.split_stop(s, probs, action, ctx)
        if action == "yield" and s._called_floor_protected():
            await s.send(type="decision", what="floor", action="carry_on", probs=probs, shielded=True)
            return
        await s.send(type="decision", what="floor", action=action, probs=probs)
        if action == "carry_on":
            if s.speaking and s.utt is not None:            # said over a line that goes on: into the call's record at once
                s.ledger.said_over(s.utt.text, s.utt)       # (not a turn to answer); the next sound starts from nothing
                s.utt, s.judged = None, None
            elif s.utt is not None:
                s.utt.over_ms = s.utt.over_ask_at = 0
        elif action == "finish_first":
            if s.utt is not None:
                s.utt.over_ms = s.utt.over_ask_at = 0
            await s.send(type="finish_line", gen=s.gen)     # the queued lines are dropped; their turn comes after
        elif action == "yield":
            await s._stop_line()                            # the utterance goes on and is answered when it ends
        else:                                               # overrule / aside / jump_in: a word now
            await s._stop_line()
            await s.respond(action)


FLOOR = Floor()
