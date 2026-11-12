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
    levels: list[float] = field(default_factory=list)   # dB of each voiced frame

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


def is_far(utt: Utterance | None, caller_levels: list[float], far_db: float | None) -> bool:
    """This voice is far_db or more under the caller's answered words: someone farther from the phone (Config.far_db)."""
    if far_db is None or utt is None or utt.level is None or not caller_levels:
        return False
    return statistics.median(caller_levels) - utt.level >= far_db
