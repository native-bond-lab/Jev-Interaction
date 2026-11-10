"""How a decision turns Jev's probabilities into an action. The questions stay the same; the policy is the business's.

    SamplePolicy     draw once against the probabilities: the same moment goes differently each time (companions)
    ThresholdPolicy  act only when a choice is at least this likely (support lines that must be predictable)
    ArgmaxPolicy     the most likely choice, always

Every decision in Config.policies names one of these; `allowed` lets the session remove choices that do not apply now
(e.g. hang_up after a short pause) and the remaining mass is renormalised before the policy sees it.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Iterable


def restrict(probs: dict[str, float], allowed: Iterable[str] | None) -> dict[str, float]:
    p = {k: v for k, v in probs.items() if allowed is None or k in set(allowed)}
    tot = sum(p.values())
    return {k: v / tot for k, v in p.items()} if tot > 0 else {}   # nothing allowed has any mass: no choice


class Policy:
    def choose(self, probs: dict[str, float], allowed: Iterable[str] | None = None) -> str | None:
        raise NotImplementedError

    def draw(self, p: float) -> bool:
        """A yes / no decision with probability p (answer now? make a sound?)."""
        raise NotImplementedError


@dataclass
class SamplePolicy(Policy):
    rng: Callable[[], float] = field(default=random.random)

    def choose(self, probs, allowed=None):
        p = restrict(probs, allowed)
        roll = self.rng()
        for k, v in p.items():
            roll -= v
            if roll < 0:
                return k
        return next(iter(p), None)

    def draw(self, p):
        return self.rng() < p


@dataclass
class ThresholdPolicy(Policy):
    thresholds: dict[str, float] = field(default_factory=dict)
    default: float = 0.5
    fallback: str | None = None

    def choose(self, probs, allowed=None):
        p = restrict(probs, allowed)
        ok = [(v, k) for k, v in p.items() if v >= self.thresholds.get(k, self.default)]
        return max(ok)[1] if ok else self.fallback

    def draw(self, p):
        return p >= self.default


@dataclass
class ArgmaxPolicy(Policy):
    def choose(self, probs, allowed=None):
        p = restrict(probs, allowed)
        return max(p, key=p.get) if p else None

    def draw(self, p):
        return p >= 0.5
