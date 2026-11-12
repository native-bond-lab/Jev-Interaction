"""TEN VAD (Agora, numpy only): the neural voice detector our production calls run on. `pip install ten-vad`
(on Linux it needs libc++: `apt-get install libc++1`).

A loud room, a keyboard, the agent's own voice coming back off a speaker all clear an energy bar; a neural detector asks
whether it is a voice. While the agent's line is playing the bar is raised a little more, as in production, so its own
echo does not pause it.
"""
from __future__ import annotations

import numpy as np


class TenVAD:
    def __init__(self, threshold: float = 0.5, play_bonus: float = 0.15, min_voiced_ms: int = 60, hop: int = 256,
                 sample_rate: int = 16000):
        from ten_vad import TenVad
        self._ten = TenVad(hop_size=hop, threshold=threshold)
        self.threshold, self.play_bonus, self.min_voiced_ms = threshold, play_bonus, min_voiced_ms
        self.hop, self.hop_ms = hop, hop * 1000 // sample_rate
        self._carry = np.zeros(0, dtype=np.int16)

    def voiced_ms(self, pcm: bytes, playing: bool = False) -> int:
        """How much of this frame is voice. Leftover samples carry into the next frame."""
        x = np.frombuffer(pcm, dtype=np.int16)
        buf = np.concatenate([self._carry, x]) if len(self._carry) else x
        n = len(buf) // self.hop
        self._carry = buf[n * self.hop:]
        bar = self.threshold + (self.play_bonus if playing else 0.0)
        # the first hops after start can come back as -1 while the model warms up: not a voice
        return sum(float(self._ten.process(h)[0]) >= bar for h in buf[: n * self.hop].reshape(n, self.hop)) * self.hop_ms

    def is_voice(self, pcm: bytes) -> bool:
        return self.voiced_ms(pcm) >= self.min_voiced_ms
