"""Something changed in view on a video call: does the agent say something about it, unasked?

The page watches the camera and sends a picture only when the view has changed enough (client.js, `watch`); the seer
puts it into one sentence, which goes into the record for every reader (Session.see). This decision is asked once per
sight, as soon as the line is free: nobody talking, nothing being said or written. While the user talks the sight
simply waits in the record, and the reply that follows already knows it. A sight left unasked for
Config.notice_stale_s has passed. Jev picks the moment; what is said is the responder's, from the same record.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision


class Notice(Decision):
    name = "notice"
    policy = "notice"

    async def on_tick(self, s, now):
        if s.sight_pending is None:
            return False
        at, seen = s.sight_pending
        if now - at > s.cfg.notice_stale_s:
            s.sight_pending = None
        elif s.utt is None and not s.speaking and not s.generating:
            s.sight_pending = None
            s._spawn(self.ask(s, seen=seen))
        return False

    def questions(self, s, ctx):
        return {"notice": Q.notice(s.p.short)}

    def state(self, s, ctx):
        return super().state(s, ctx) + S.notice(s.p.short, ctx["seen"], s.remarks_on_view)

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating and s.utt is None

    async def apply(self, s, answers, ctx):
        choice = self.choose(s, answers, "notice", ctx)
        await s.send(type="decision", what="notice", action=choice, seen=ctx["seen"], probs=P(answers, "notice"))
        if choice == "remark":
            s.remarks_on_view += 1
            await s.respond("notice")


NOTICE = Notice()
