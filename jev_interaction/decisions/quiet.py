"""Quiet on the line since the agent's last line: pick the thread up, check on them, let it be, or hang up.

Asked at the (jittered) marks in Config.quiet_marks_s. Checking needs Config.check_min_quiet_s of quiet; hanging up
needs Config.hangup_min_quiet_s and is never the first thing said into a quiet. A judge that fails says nothing.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision

LINES = {"go_on": "lead", "check": "check", "hang_up": "hangup"}     # choice -> the kind of line the agent says


class Quiet(Decision):
    name = "quiet"
    policy = "quiet"

    async def on_tick(self, s, now):
        if s.utt is None and not s.speaking and not s.generating and s.quiet_marks:
            quiet_s = now - s.idle_since
            if quiet_s >= s.quiet_marks[0]:
                s.quiet_marks.pop(0)
                s._spawn(self.ask(s, quiet_s=quiet_s))
        return False

    def questions(self, s, ctx):
        return {"quiet": Q.quiet(s.p.short, s.pace)}

    def state(self, s, ctx):
        last = s.ledger.last_agent()
        gaps = sorted(s.reply_gaps)
        usual = gaps[len(gaps) // 2] if len(gaps) >= 2 else None
        return super().state(s, ctx) + S.quiet(s.p.short, last.text if last else "", ctx["quiet_s"], s.spoke_into_quiet, usual)

    def allowed(self, s, ctx):
        allowed = ["go_on", "wait"]
        if ctx["quiet_s"] >= s.cfg.check_min_quiet_s:
            allowed.append("check")
        if ctx["quiet_s"] >= s.cfg.hangup_min_quiet_s and s.spoke_into_quiet:
            allowed.append("hang_up")
        return allowed

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating and s.utt is None

    async def apply(self, s, answers, ctx):
        quiet_s = ctx["quiet_s"]
        choice = self.choose(s, answers, "quiet", ctx)
        await s.send(type="decision", what="quiet", action=choice, quiet_s=round(quiet_s, 1), probs=P(answers, "quiet"))
        if choice in LINES:
            s.spoke_into_quiet += 1
            s.hanging_up = choice == "hang_up"
            await s.respond(LINES[choice], quiet_s=quiet_s)


QUIET = Quiet()
