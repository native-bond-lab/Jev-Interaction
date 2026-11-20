"""Something changed in view on a video call: does the agent say something about it, unasked?

With Config.jev_sees Jev is shown two pictures, the last one that was news and the newest, as soon as the line is free;
the responder is shown the newest when it speaks, and the seer (if any) writes the record line afterwards, off the
path. Otherwise, as below:

The page watches the camera and sends a picture only when the view has changed enough (client.js, `watch`); the seer
puts it into one sentence, which goes into the record for every reader (Session.see). This decision is asked once per
sight, as soon as the line is free: nobody talking, nothing being said or written. While the user talks the sight
simply waits in the record, and the reply that follows already knows it. A sight left unasked for
Config.notice_stale_s has passed. Jev picks the moment (and whether it is one the user asked to be told about); what is said is the
responder's, from the same record.
"""
from __future__ import annotations

import base64

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision

BEFORE, NOW = "c1f4e9a2-picture-before", "7b3d0e58-picture-now"     # asset keys: long, so no other text can match them


class Notice(Decision):
    name = "notice"
    policy = "notice"

    async def on_tick(self, s, now):
        if s.cfg.jev_sees:                       # Jev looks itself: the newest picture, once the line is free
            if s.frame_fresh and s.sight_image is not None and not s.speaking and not s.generating:
                s.frame_fresh = False                # asked while the user talks too: then only what they asked for
                s._spawn(self.ask(s, now_image=s.frame_now, before_image=s.sight_image, seen="", talking=s.utt is not None))
            return False
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
        if "now_image" in ctx:
            return super().state(s, ctx) + S.notice_pictures(s.p.short, BEFORE, NOW, s.remarks_on_view, bool(ctx.get("talking")))
        return super().state(s, ctx) + S.notice(s.p.short, ctx["seen"], s.remarks_on_view)

    def assets(self, s, ctx):
        if "now_image" not in ctx:
            return None
        pic = lambda b: dict(type="image", format="jpg", data_base64=base64.b64encode(b).decode())   # noqa: E731
        return {BEFORE: pic(ctx["before_image"]), NOW: pic(ctx["now_image"])}

    def allowed(self, s, ctx):
        # the user is talking: only what they asked to be told about cuts in (as a listener says what was asked for)
        return ["due", "let_be"] if ctx.get("talking") else None

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating and (ctx.get("talking") or s.utt is None)

    async def apply(self, s, answers, ctx):
        choice = self.choose(s, answers, "notice", ctx)
        await s.send(type="decision", what="notice", action=choice, seen=ctx["seen"], probs=P(answers, "notice"))
        if choice in ("due", "remark"):          # due: what the user asked to be told about has shown up
            s.remarks_on_view += 1
            image = ctx.get("now_image")
            if image is not None:                # this picture is the news now: later ones are compared with it
                s._spawn(s.record_sight(ctx["before_image"], image))
                s.sight_image = image
            await s.respond("notice_due" if choice == "due" else "notice", image=image)


NOTICE = Notice()
