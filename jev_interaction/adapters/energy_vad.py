from __future__ import annotations

import numpy as np


class EnergyVAD:
    """A frame is voice when enough 20 ms sub-frames rise well above the running noise floor. Good enough with headphones
    in a quiet room, and what `best_vad()` falls back to; TenVAD (ten_vad.py) is the detector production runs on."""

    def __init__(self, sample_rate: int = 16000, ratio: float = 3.0, floor: float = 0.012, min_voiced_ms: int = 60,
                 play_gain: float = 2.5):
        self.sub = sample_rate // 50
        self.ratio, self.floor, self.min_voiced = ratio, floor, min_voiced_ms // 20
        self.play_gain = play_gain                # the bar is this much higher while the agent's line plays (its echo)
        self.noise = 0.005

    def voiced_ms(self, pcm: bytes, playing: bool = False) -> int:
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        n = len(x) // self.sub * self.sub
        if not n:
            return 0
        rms = np.sqrt(np.mean(x[:n].reshape(-1, self.sub) ** 2, axis=1))
        voiced = int(np.sum(rms > max(self.floor, self.noise * self.ratio) * (self.play_gain if playing else 1.0)))
        if voiced < self.min_voiced:
            self.noise = 0.95 * self.noise + 0.05 * float(np.median(rms))
        return voiced * 20

    def is_voice(self, pcm: bytes) -> bool:
        return self.voiced_ms(pcm) >= self.min_voiced * 20
