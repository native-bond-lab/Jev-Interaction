"""What the user is saying right now: the words the recognizer has closed so far, how long and how loud the voice was.

An utterance opens with the first voiced frame (or the first recognized words) and ends when it is answered, dropped as
not said to the agent, or released as a wordless sound over the agent's line.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np


def frame_db(pcm: bytes) -> float:
    """Loudness of one PCM16 frame in dB (0 dB = full scale)."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    return 20 * math.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-6) if len(x) else -120.0


@dataclass
class Utterance:
    id: int
    started: float
    segments: list[tuple[float, str]] = field(default_factory=list)
    speech_ms: int = 0
    over: bool = False               # began while the agent was speaking
    over_ms: int = 0                 # voice over the agent's line since it last went on: what a hold is measured on
    held_at: int = 0                 # how many segments there were when the line was put on hold
    levels: list[float] = field(default_factory=list)   # dB of each voiced frame
    marking: bool = False            # the agent is making the marks the user asked for: its voice is kept for those
    # what the agent put in with content while the user talked on: (segments heard by then, its words, the line the
    # responder was given for it)
    asides: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def level(self) -> float | None:
        """How loud the voice was: the louder half of its voiced frames, in dB (pauses do not count)."""
        if not self.levels:
            return None
        top = sorted(self.levels)[len(self.levels) // 2:]
        return sum(top) / len(top)

    @property
    def text(self) -> str:
        return " ".join(x for _, x in self.segments)

    def with_asides(self, name: str) -> str:
        """The words with what the agent put in at the place it came ("... the vase, [Lyra: one] water everywhere ..."):
        the turn as one text, for Jev's recent turns. Bare listening sounds are not in it."""
        out = []
        for i, (_, words) in enumerate(self.segments, 1):
            out.append(words)
            out += [f"[{name}: {said}]" for at, said, _ in self.asides if at == i]
        return " ".join(out)

    def exchanges(self) -> tuple[list[tuple[str, str, str]], str]:
        """The turn as it went, for the responder: (the user's words up to there, what the agent put in, the line it
        was given), one for each aside in order, then the words since the last one."""
        done, start = [], 0
        for at, said, line in sorted(self.asides, key=lambda a: a[0]):
            done.append((" ".join(x for _, x in self.segments[start:at]), said, line))
            start = max(start, at)
        return done, " ".join(x for _, x in self.segments[start:])


def is_far(utt: Utterance | None, caller_levels: list[float], far_db: float | None) -> bool:
    """This voice is far_db or more under the caller's answered words: someone farther from the phone (Config.far_db)."""
    if far_db is None or utt is None or utt.level is None or not caller_levels:
        return False
    return statistics.median(caller_levels) - utt.level >= far_db
