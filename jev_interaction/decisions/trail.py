"""The user said something and went silent, and nobody judged them finished: speak now, or leave the silence to them?

The end-of-turn question (turn.py) is asked while the user pauses; when the pace's longest wait has run out and Jev was
never sure they had finished, a clock used to hand the turn to the agent. A responder asked to write a line writes one,
whatever the user had asked for ("I'll keep talking, only count the cats"), so whether to speak is decided here, before
it is asked: by Jev, on the same record. Asked again after more silence (Config.trail_marks_ms); at the last mark the
agent speaks anyway, as a person does after a long silence. A judge that fails answers "take_up", the old behaviour.
"""
from __future__ import annotations

import time

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision


class Trail(Decision):
    name = "trail"
    policy = "trail"

    async def on_tick(self, s, now):
        u = s.utt
        if u is None or not u.segments or s.silence_ms <= 0 or s.speaking or s.generating:
            return False
        if u.trail_at != len(u.segments):                     # new words since: the marks start over
            u.trail_at, u.trail_asked = len(u.segments), 0
        marks = s.cfg.trail_marks_ms
        if u.trail_asked >= len(marks) or s.silence_ms < s.params().max_wait_ms + 1000 + marks[u.trail_asked]:
            return False
        u.trail_asked += 1
        if u.trail_asked == len(marks):                       # a long silence after their words: the agent speaks
            await self.take_up(s)
            return True
        s._spawn(self.ask(s, utt_id=u.id, segments=len(u.segments), quiet_s=s.silence_ms / 1000))
        return False

    def questions(self, s, ctx):
        return {"trail": Q.trail(s.p.short, ctx["quiet_s"])}

    def state(self, s, ctx):
        return super().state(s, ctx) + S.user_turn(s.p.short, s.utt.segments, time.monotonic(), s.silence_ms, s.speaking,
                                                    s.utt.asides)

    def current(self, s, ctx):
        return (s.utt is not None and s.utt.id == ctx["utt_id"] and len(s.utt.segments) == ctx["segments"]
                and s.silence_ms > 0 and not s.speaking and not s.generating)

    async def apply(self, s, answers, ctx):
        probs = P(answers, "trail")
        choice = self.choose(s, answers, "trail", ctx) or "take_up"
        await s.send(type="decision", what="trail", action=choice, quiet_s=round(ctx["quiet_s"], 1), probs=probs)
        if choice == "take_up":
            await self.take_up(s)

    async def take_up(self, s):
        if s._far():
            await s._not_for_me("far")
        else:
            await s.respond("trailed", quiet_s=s.silence_ms / 1000)


TRAIL = Trail()
