"""The user is talking and the agent listens: a listening sound of some kind, or none.

Carried by the turn question (turn.py asks both in one request, so it costs no extra call), at most once every
Config.listen_gap_s, and never once Jev is fairly sure the user has finished. The sound itself is `Session.listen_in`.
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
        gap = min(s.cfg.listen_gap_s, s.cfg.listen_receipt_gap_s)       # a piece said back may follow sooner
        return not s.speaking and not s.generating and time.monotonic() - s.listen_last >= gap

    def questions(self, s, ctx):
        return {"listen": Q.listen(s.p.short)}

    def state(self, s, ctx):
        segments = s.utt.segments if s.utt else []
        return super().state(s, ctx) + S.user_turn(s.p.short, segments, time.monotonic(), s.silence_ms, s.speaking,
                                                    s.utt.asides if s.utt else ())

    async def apply(self, s, answers, ctx):
        lp = P(answers, "listen")
        kinds = {k: lp.get(k, 0.0) for k in Q.LISTEN_KINDS}       # quiet and answer_due are the mass for "no sound"
        if s.utt is None or (s.utt.id, len(s.utt.segments)) == s.listen_at:
            kinds = {k: v for k, v in kinds.items() if k not in Q.LISTEN_PER_PIECE}   # once: nothing new has landed
        if time.monotonic() - s.listen_last < s.cfg.listen_gap_s:
            kinds = {k: v for k, v in kinds.items() if k in Q.LISTEN_PER_PIECE}       # the other sounds keep their distance
        policy = self.policy_for(s, ctx)
        finished = s.judged["finished"] if s.judged else 0.0
        piece = {k: kinds.pop(k) for k in Q.LISTEN_PER_PIECE if k in kinds}   # exact work (a count, a list): not drawn
        best = max(piece, key=piece.get, default=None)
        if best and piece[best] >= s.cfg.listen_piece_min:
            s._spawn(s.listen_in(best))
        elif kinds and finished < s.cfg.listen_finished_max and policy.draw(sum(kinds.values())):
            s._spawn(s.listen_in(policy.choose(kinds) or "continuer"))

    def invite(self, s):
        """The end-of-turn draw said "not yet": half the time, a questioning sound that invites the user on."""
        if self.policy_for(s, ctx={}).draw(0.5):
            s._spawn(s.listen_in("continuer", inviting=True))


LISTEN = Listen()
