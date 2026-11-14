"""The user pauses while talking: have they finished, how long to wait, a reply or a sound, which pace.

Asked on every new segment of words, and again as the quiet grows (Config.turn_reask_ms) if the last draw said "not
yet". The answer is kept on the session (`judged`); the tick draws against p(finished) once the quiet reaches the wait
Jev suggested. The listen question rides in the same request (listen.py), so while the user is not judged finished the
agent is still listening: a sound may slip in, the turn is not taken. Only when the quiet has outlasted the pace's
longest wait by Config.turn_last_ms with Jev never sure does the agent speak anyway, and its line is told so ("trailed").
"""
from __future__ import annotations

import time

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision
from .handover import HANDOVER
from .listen import LISTEN


class Turn(Decision):
    name = "turn"
    policy = "end_of_turn"

    def on_words(self, s):
        if not s.speaking and not s.generating:
            s._spawn(self.ask(s, utt_id=s.utt.id))

    def ready(self, s, ctx):
        return s.utt is not None

    def questions(self, s, ctx):
        paces = {p.name: p.description for p in s.cfg.paces}
        qs = Q.turn(s.p.short, s.pace, paces, opening=s.user_turns < s.cfg.opening_turns)
        ctx["may_listen"] = LISTEN.ready(s, ctx)
        if ctx["may_listen"]:
            qs.update(LISTEN.questions(s, ctx))
        if HANDOVER.ready(s, ctx):
            qs.update(HANDOVER.questions(s, ctx))
        if s._offer_elsewhere():
            qs["kind"]["criteria"]["elsewhere"] = Q.elsewhere(s.p.short)
        return qs

    def state(self, s, ctx):
        return super().state(s, ctx) + S.user_turn(s.p.short, s.utt.segments, time.monotonic(), s.silence_ms, s.speaking,
                                                    s.utt.asides)

    def current(self, s, ctx):
        return s.utt is not None and s.utt.id == ctx["utt_id"]      # still the same utterance

    async def apply(self, s, answers, ctx):
        kind = P(answers, "kind")
        if s._far() or (s._offer_elsewhere() and kind and max(kind, key=kind.get) == "elsewhere"):
            await s._not_for_me("far" if s._far() else "jev")
            return
        await s._update_pace(P(answers, "pace"))
        wait = P(answers, "wait")                                   # a failed judge: no wait, p(finished) 0, so the
        s.judged = {"finished": P(answers, "done").get("finished", 0.0),   # turn is answered at the pace's longest wait
                    "wait_ms": int(sum(Q.WAIT_MS[k] * v for k, v in wait.items())),
                    "reply": kind.get("reply", 1.0), "drawn": False,
                    "who": HANDOVER.chosen(s, answers, ctx) if HANDOVER.ready(s, ctx) else None}
        if ctx["may_listen"]:
            await LISTEN.apply(s, answers, ctx)

    async def on_tick(self, s, now):
        if s.utt is None or not s.utt.segments or s.silence_ms <= 0 or s.speaking or s.generating:
            return False
        pace = s.params()
        j = s.judged
        if j and not j["drawn"] and s.silence_ms >= min(j["wait_ms"], pace.max_wait_ms):
            j["drawn"] = True                 # one draw per Jev answer; new words or more quiet bring a new answer
            go = self.policy_for(s, ctx={}).draw(j["finished"])
            await s.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2), go=go)
            if go:
                await self.answer(s)
                return True
        if s.silence_ms >= pace.max_wait_ms + s.cfg.turn_last_ms:
            await self.answer(s, "trailed")   # a long silence after their words: the agent speaks, as a person does
            return True
        if (j is None or j["drawn"]) and s.silence_ms in s.cfg.turn_reask_ms:   # also words nobody has judged yet (said
                                                                                # over a line that then ended)
            s._spawn(self.ask(s, utt_id=s.utt.id))
        return False

    async def answer(self, s, kind: str = "spoke"):
        """Answer what the user said, unless the voice was someone else's (Config.far_db)."""
        if s._far():
            await s._not_for_me("far")
        elif s.judged and s.judged.get("who"):
            await s.hand_over(s.judged["who"])            # they asked for someone else: a word, then the other comes on
        else:
            await s.respond(kind, quiet_s=s.silence_ms / 1000)


TURN = Turn()
