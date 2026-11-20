"""What the agent is for, for the two readers that need it.

A profile describes a task type (a companion, a support line, a tutor, an interviewer…) or one character within it.
`prompt` goes to the responder: what the agent says. `manner` goes to Jev: how the agent behaves on a call, whether it
makes listening sounds, how long it lets a pause stand, whether it yields when talked over, whether it speaks into a
silence. Turn-detection models only hear audio and words; here the same moment is judged differently per task.

A profile may also carry its own decision policies (`policies: {floor: threshold, quiet: argmax}`): a companion draws
against Jev's probabilities so the same moment goes differently each time, a support line acts only on confident answers.

And its own turn-taking (`turn_taking`): the questions Jev is asked are the same whoever the agent is, and what the
persona changes is the thresholds and the timing the pace opens. A dominant character's line is harder to stop and it
cuts in; a gentle one stops at once, never cuts in and lets a quiet run longer.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field, replace

import yaml

from .policy import ArgmaxPolicy, Policy, SamplePolicy, ThresholdPolicy

BUILTIN = pathlib.Path(__file__).resolve().parent / "profiles"     # the shipped personas
POLICY_NAMES = {"sample": SamplePolicy, "argmax": ArgmaxPolicy, "threshold": ThresholdPolicy}


@dataclass(frozen=True)
class TurnTaking:
    """How a persona takes turns, on top of the pace it is in (Pace). Measured with tools/persona_bench.py: two personas
    with opposite settings act alike in everyday moments and differently where a scene calls for it."""
    yield_shift: float = 0.0        # added to the pace's yield_p (how sure Jev must be that the user wants the floor before
                                    # the line stops): + harder to stop, - stops sooner. Kept within 0.15 .. 0.9
    cut_in: str = "pace"            # "always": cuts in and takes the floor back in any pace; "never": in none; "pace": as
                                    # the pace says
    lead_scale: float = 1.0         # scales how long a quiet after its own line lasts before it picks the thread up

    def __post_init__(self):
        if self.cut_in not in ("pace", "always", "never"):
            raise ValueError(f"turn_taking.cut_in is pace, always or never, not {self.cut_in!r}")
        if self.lead_scale <= 0:
            raise ValueError("turn_taking.lead_scale must be above 0")

    def apply(self, pace):
        """The pace as this persona takes it. `leads` is the pace's own: a persona that cuts in still finishes its
        sentence first when talked over in a pace that does not lead."""
        cut = {"always": True, "never": False}.get(self.cut_in, pace.cut_in)
        return replace(pace, yield_p=min(0.9, max(0.15, pace.yield_p + self.yield_shift)), cut_in=cut,
                       lead_after_s=pace.lead_after_s * self.lead_scale)


@dataclass
class Profile:
    name: str                       # how the agent is called on the line ("Mara", "the assistant")
    task: str = ""                  # the task type in a sentence: what the call is for
    prompt: str = ""                # for the responder
    manner: str = ""                # for Jev
    policies: dict[str, Policy] = field(default_factory=dict)
    turn_taking: TurnTaking = field(default_factory=TurnTaking)
    extra: dict = field(default_factory=dict)

    @property
    def short(self) -> str:
        return self.name.split()[0] if self.name else "the agent"

    def judge_header(self) -> str:
        parts = [f"Who {self.short} is: {self.task}".rstrip(": ")]
        if self.manner:
            parts.append(f"On the call: {self.manner}")
        return " ".join(parts)

    @classmethod
    def load(cls, path: str | pathlib.Path) -> Profile:
        """A profile from a YAML file, or a built-in one by name ("support", "vera", ...)."""
        p = pathlib.Path(path)
        if not p.exists() and p.suffix == "" and len(p.parts) == 1:
            p = BUILTIN / f"{p.name}.yaml"
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        policies = {}
        for decision, spec in (d.get("policies") or {}).items():
            spec = {"type": spec} if isinstance(spec, str) else dict(spec)
            kind = POLICY_NAMES[spec.pop("type")]
            policies[decision] = kind(**spec)
        known = ("name", "task", "prompt", "manner", "policies", "turn_taking")
        return cls(name=d["name"], task=d.get("task", ""), prompt=d.get("prompt", ""), manner=d.get("manner", ""),
                   policies=policies, turn_taking=TurnTaking(**(d.get("turn_taking") or {})),
                   extra={k: v for k, v in d.items() if k not in known})
