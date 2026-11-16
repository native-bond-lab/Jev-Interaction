"""Someone else can be put on the line (a profile's `cast`): is the user asking for one of them now?

Carried by the turn question, like listen (turn.py asks both in one request), and only when the session has a cast.
Jev's answer is kept with the turn's; when the turn is taken and Jev is sure, the agent on the line says so in a few
words and the other comes on with their own voice, manner and policies (`Session.hand_over`). Nothing here knows what
either of them says: the words are the responder's.
"""
from __future__ import annotations

from ..judge import questions as Q
from ..judge.client import probs as P
from .base import Decision


class HandOver(Decision):
    name = "who"
    policy = "who"

    def ready(self, s, ctx):
        return bool(s.others())

    def questions(self, s, ctx):
        return {"who": Q.who(s.p.short, {pid: (p.short, p.task) for pid, p in s.others().items()})}

    def chosen(self, s, answers, ctx) -> str | None:
        """The id of the one the user asked for, or None to stay."""
        choice = self.policy_for(s, ctx).choose(P(answers, "who"), ["stay", *s.others()])
        return choice if choice in s.others() else None


HANDOVER = HandOver()
