"""A decision: one moment of the call put to Jev as a question, and what the answer does.

A decision says when it is asked (`on_words`, `on_tick`), what Jev is asked (`questions`) about which state (`state`),
which choices apply right now (`allowed`), and what the policy's choice does to the call (`apply`). The session only
feeds it the call; everything that is particular to the decision lives in its module. Decisions are the session's own
parts, so they use its helpers freely (`_spawn`, `_ask`, `_stop_line`, `_not_for_me`, `respond`).

`ctx` is the moment's scratch pad, one dict per ask: the caller's arguments (`session.ask("quiet", quiet_s=12.0)`) plus
whatever `questions` notes for `apply` (the choices it offered, the pace it saw).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from ..judge import state as S
from ..judge.client import probs as P
from ..policy import Policy

if TYPE_CHECKING:
    from ..session import Session


class Decision:
    name: str = ""       # the purpose in the call log, and what `session.ask(name)` and tools/replay.py call it
    policy: str = ""     # the key in Config.policies (and a profile's policies) that turns probabilities into a choice

    # ---------------------------------------------------------------- when
    def on_words(self, s: Session) -> None:
        """The recognizer closed a segment of the user's words. `s._spawn(self.ask(s, ...))` if this is the moment."""

    async def on_tick(self, s: Session, now: float) -> bool:
        """Every 100 ms. True when it just changed the call (answered, dropped the words): the decisions after it then
        wait for the next tick instead of reading a call that moved under them."""
        return False

    def ready(self, s: Session, ctx: dict) -> bool:
        """Is there anything to ask about right now?"""
        return True

    # ---------------------------------------------------------------- what
    def questions(self, s: Session, ctx: dict) -> dict:
        """{question name: question dict}, built with judge/questions.py."""
        raise NotImplementedError

    def state(self, s: Session, ctx: dict) -> str:
        """The text Jev reads. The header (who, the task profile, the pace, the recent turns) opens every state."""
        return S.header(s.p, s.pace, s.ledger, s.cfg.judge_turns, s.cfg.judge_turn_chars)

    def allowed(self, s: Session, ctx: dict) -> Iterable[str] | None:
        """The choices that apply right now; None for all of them."""
        return None

    def current(self, s: Session, ctx: dict) -> bool:
        """The answer is back: is the call still at the moment that was asked about?"""
        return ctx["gen"] == s.gen

    # ---------------------------------------------------------------- then
    def policy_for(self, s: Session, ctx: dict) -> Policy:
        return s.policies[self.policy or self.name]

    def choose(self, s: Session, answers: dict, key: str, ctx: dict) -> str | None:
        """The policy's choice among the allowed ones; None when the judge gave nothing (each decision has a fallback)."""
        return self.policy_for(s, ctx).choose(P(answers, key), self.allowed(s, ctx))

    async def apply(self, s: Session, answers: dict, ctx: dict) -> None:
        """Turn the answer into actions on the session. `answers` is {} when the judge failed or was slow."""
        raise NotImplementedError

    async def ask(self, s: Session, **ctx) -> None:
        """One round: ask Jev, then apply the answer if the moment has not passed. Never two rounds of one decision at once."""
        if self.name in s.busy or not self.ready(s, ctx):
            return
        s.busy.add(self.name)
        try:
            questions, state = self.questions(s, ctx), self.state(s, ctx)
            ctx.setdefault("gen", s.gen)
            answers = await s._ask(self.name, questions, state)
            if self.current(s, ctx):
                await self.apply(s, answers, ctx)
        finally:
            s.busy.discard(self.name)
