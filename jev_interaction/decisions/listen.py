"""The user has the floor and the agent listens: is this a moment to put something in, or not?

Jev is asked only about the moment; what is put in (a sound, a word said back, a count the user asked for) the
responder writes from the call's record (`Session.listen_in`). Carried by the turn question (turn.py asks both in one
request, so it costs no extra call). Something the user is waiting for ("due") is made when Jev is sure of it, once
for the words that brought it up (asked again about the same words, it is not due again); a sound
that could as well be left out ("fits") is drawn by the policy, keeps Config.listen_gap_s from the last one, and is not
made once Jev is fairly sure the user has finished.
"""
from __future__ import annotations

import time

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision


class Listen(Decision):
    name = "listen"
    policy = "listen"

    def ready(self, s, ctx):
        return not s.speaking and not s.generating and time.monotonic() - s.listen_last >= s.cfg.listen_min_gap_s

    def questions(self, s, ctx):
        return {"listen": Q.listen(s.p.short)}

    def state(self, s, ctx):
        segments = s.utt.segments if s.utt else []
        return super().state(s, ctx) + S.user_turn(s.p.short, segments, time.monotonic(), s.silence_ms, s.speaking,
                                                    s.utt.asides if s.utt else ())

    async def apply(self, s, answers, ctx):
        lp = P(answers, "listen")
        due, fits = lp.get("due", 0.0), lp.get("fits", 0.0)           # quiet and answer_due are the mass for "nothing"
        finished = s.judged["finished"] if s.judged else 0.0
        # something the user is waiting for can only have "just come up" in words said since the agent last put
        # something in: the same words asked about again as the quiet grows are not a second time
        new_words = s.utt is not None and len(s.utt.segments) > (s.utt.asides[-1][0] if s.utt.asides else 0)
        if not new_words:
            due = 0.0
        if due >= s.cfg.listen_due_min:
            s._spawn(s.listen_in("due"))
        elif (time.monotonic() - s.listen_last >= s.cfg.listen_gap_s and finished < s.cfg.listen_finished_max
              and self.policy_for(s, ctx).draw(due + fits)):
            s._spawn(s.listen_in("fits"))


LISTEN = Listen()
