"""What the agent is for, for the two readers that need it.

A profile describes a task type (a companion, a support line, a tutor, an interviewer…) or one character within it.
`prompt` goes to the responder: what the agent says. `manner` goes to Jev: how the agent behaves on a call, whether it
makes listening sounds, how long it lets a pause stand, whether it yields when talked over, whether it speaks into a
silence. Turn-detection models only hear audio and words; here the same moment is judged differently per task.

A profile may also carry its own decision policies (`policies: {floor: threshold, quiet: argmax}`): a companion draws
against Jev's probabilities so the same moment goes differently each time, a support line acts only on confident answers.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

from .policy import ArgmaxPolicy, Policy, SamplePolicy, ThresholdPolicy

BUILTIN = pathlib.Path(__file__).resolve().parent / "profiles"     # the shipped personas
POLICY_NAMES = {"sample": SamplePolicy, "argmax": ArgmaxPolicy, "threshold": ThresholdPolicy}


@dataclass
class Profile:
    name: str                       # how the agent is called on the line ("Mara", "the assistant")
    task: str = ""                  # the task type in a sentence: what the call is for
    prompt: str = ""                # for the responder
    manner: str = ""                # for Jev
    policies: dict[str, Policy] = field(default_factory=dict)
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
    def load(cls, path: str | pathlib.Path) -> "Profile":
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
        known = ("name", "task", "prompt", "manner", "policies")
        return cls(name=d["name"], task=d.get("task", ""), prompt=d.get("prompt", ""), manner=d.get("manner", ""),
                   policies=policies, extra={k: v for k, v in d.items() if k not in known})
