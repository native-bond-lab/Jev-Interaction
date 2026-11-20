"""Quiet on the line since the agent's last line: pick the thread up, check on them, let it be, or hang up.

Jev is asked facts, each small and about one thing on the record: whose move the agent's last line leaves, whether the
user said they need a moment, whether goodbyes were said, whether the agent has already been calling out with no answer
(`facts`; the wordings are measured ones, in judge/bailian.py). How long the quiet has lasted is not a question: the
engine has the clock. What the agent does follows from the facts and the time (`probs`, `allowed`):

    the call has ended (goodbyes, or calling out with no answer)   hang up, once Config.hangup_min_quiet_s has passed
                                                                   and something has already been said into the quiet
    the next move is the agent's own (its line was a statement)    pick the thread up, after the pace's lead_after_s
    the next move is the user's (asked something, or they are      let it be; after Config.check_min_quiet_s, check on
    busy with something)                                           them

The policy under "quiet" turns that into the one action. By default it is a threshold, so the same quiet goes the same
way every time; what varies from one quiet to the next is when it is asked (Config.quiet_marks_s, jittered). A judge
that fails says nothing.

While a background task is unfinished (tasks.py) the call has something to wait for: it is not hung up, and once the
quiet has lasted Config.sleep_after_s the session goes to sleep and this question is not asked again until it wakes
(Session.sleep). Under Config.sleep_when_idle the agent does not check on the user either: a quiet is them working.

Asked as one question about the whole quiet ("would the agent, being who they are, say something now?"), Jev answered
"let it be" to nearly every written moment (33% right on tools/judge_bench.py --decisions); asked the facts, 100%.
"""
from __future__ import annotations

from ..judge import bailian as B
from ..judge.client import probs as P
from .base import Decision

LINES = {"go_on": "lead", "check": "check", "hang_up": "hangup"}     # choice -> the kind of line the agent says


def facts() -> dict:
    """The questions, each asked with its options in both orders (a judge that leans to the first cancels out)."""
    return {**B.both("turn", B.TURN), **B.both("busy", B.BUSY), **B.both("bye", B.BYE), **B.both("gone", B.GONE)}


def probs(answers: dict, *, long: bool, may_hang_up: bool = True) -> dict[str, float]:
    """How likely each thing to do is, from the facts (merged answers). The move is the user's when the agent's line
    left them something or they said they are busy; the call has ended on goodbyes or on calling out with no answer.
    The clock is the engine's, not the judge's: `long`, the quiet has lasted long enough to check on them;
    `may_hang_up`, hanging up is open. An ended call that may not be hung up yet is a quiet that is theirs: let it be,
    then check on them, and the hang-up follows that."""
    if "turn" not in answers:
        return {}
    yes = lambda name, choice: P(answers, name).get(choice, 0.0)  # noqa: E731
    theirs = 1 - (1 - yes("turn", "theirs")) * (1 - yes("busy", "busy"))
    ended = 1 - (1 - yes("bye", "goodbye")) * (1 - yes("gone", "unanswered"))
    waiting = (1 - ended) * theirs + (0.0 if may_hang_up else ended)
    return {"go_on": (1 - ended) * (1 - theirs), "wait": 0.0 if long else waiting, "check": waiting if long else 0.0,
            "hang_up": ended if may_hang_up else 0.0}


def allowed(quiet_s: float, spoke: int, *, lead_after_s: float, check_after_s: float, hangup_after_s: float) -> list[str]:
    """What the clock opens: letting it be always, the rest once the quiet has lasted long enough."""
    out = ["wait"]
    if quiet_s >= lead_after_s:
        out.append("go_on")
    if quiet_s >= check_after_s:
        out.append("check")
    if quiet_s >= hangup_after_s and spoke:        # never the first thing said into a quiet
        out.append("hang_up")
    return out


class Quiet(Decision):
    name = "quiet"
    policy = "quiet"

    async def on_tick(self, s, now):
        if s.utt is None and not s.speaking and not s.generating and s.quiet_marks and not s.asleep:
            quiet_s = now - s.idle_since
            if quiet_s >= s.quiet_marks[0]:
                s.quiet_marks.pop(0)
                s._spawn(self.ask(s, quiet_s=quiet_s))
        return False

    def questions(self, s, ctx):
        return facts()

    def state(self, s, ctx):
        """The same account as every state, with what the questions point at in fields of their own."""
        text, m = super().state(s, ctx), ctx["now"]
        said = B.earlier_user_lines(s.ledger, s.cfg.judge_turns)
        return B.quiet_state(text, m.agent_line, said[-1] if said else "", m.quiet_s, m.spoke_into_quiet, s.pace)

    def allowed(self, s, ctx):
        out = allowed(ctx["quiet_s"], s.spoke_into_quiet, lead_after_s=s.params().lead_after_s,
                      check_after_s=s.cfg.check_min_quiet_s, hangup_after_s=s.cfg.hangup_min_quiet_s)
        if s.cfg.sleep_when_idle:              # on a desk all day: a quiet is the user working, not a call gone dead
            return [x for x in out if x not in ("check", "hang_up")]
        return [x for x in out if x != "hang_up"] if s.open_tasks() else out

    def current(self, s, ctx):
        return ctx["gen"] == s.gen and not s.speaking and not s.generating and s.utt is None and not s.asleep

    async def apply(self, s, answers, ctx):
        quiet_s = ctx["quiet_s"]
        ps = probs(B.merge(answers), long=quiet_s >= s.cfg.check_min_quiet_s, may_hang_up="hang_up" in self.allowed(s, ctx))
        choice = self.choose(s, {"quiet": {"probabilities": ps}}, "quiet", ctx)
        await s.send(type="decision", what="quiet", action=choice, quiet_s=round(quiet_s, 1), probs=ps)
        if choice in LINES:
            s.spoke_into_quiet += 1
            s.hanging_up = choice == "hang_up"
            await s.respond(LINES[choice], quiet_s=quiet_s)


QUIET = Quiet()
