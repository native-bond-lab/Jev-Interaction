"""The interaction decisions, one module each. The questions themselves are in judge/questions.py.

    when                                   decision    module       policy key
    the user pauses while talking          turn        turn.py      end_of_turn
                                           listen      listen.py    listen        (rides in the turn request)
    both talk at once                      floor       floor.py     floor
    the user talks, the agent leads        cut_in      cut_in.py    cut_in
    the user went silent, not finished     trail       trail.py     (Jev's likeliest answer)
    quiet since the agent's last line      quiet       quiet.py     quiet

Adding a decision is one module with a Decision subclass, `register()` (or an entry in DECISIONS), and a policy under
its key in Config.policies. The order of DECISIONS is the order the session offers each new segment and each tick.
"""
from __future__ import annotations

from .base import Decision
from .cut_in import CUT_IN
from .floor import FLOOR
from .listen import LISTEN
from .quiet import QUIET
from .trail import TRAIL
from .turn import TURN

DECISIONS: dict[str, Decision] = {d.name: d for d in (TURN, TRAIL, LISTEN, FLOOR, CUT_IN, QUIET)}


def register(decision: Decision) -> Decision:
    """Add a decision to every session started from now on."""
    DECISIONS[decision.name] = decision
    return decision


__all__ = ["DECISIONS", "Decision", "register"]
