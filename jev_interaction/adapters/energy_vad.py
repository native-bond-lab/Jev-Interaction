from __future__ import annotations

import numpy as np


class EnergyVAD:
    """A frame is voice when enough 20 ms sub-frames rise well above the running noise floor. Good enough with headphones;
    use a neural VAD (TEN, Silero) behind the same `is_voice` for speakers or noisy rooms."""

    def __init__(self, sample_rate: int = 16000, ratio: float = 3.0, floor: float = 0.012, min_voiced_ms: int = 60):
        self.sub = sample_rate // 50
        self.ratio, self.floor, self.min_voiced = ratio, floor, min_voiced_ms // 20
        self.noise = 0.005

    def is_voice(self, pcm: bytes) -> bool:
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        n = len(x) // self.sub * self.sub
        if not n:
            return False
        rms = np.sqrt(np.mean(x[:n].reshape(-1, self.sub) ** 2, axis=1))
        voiced = int(np.sum(rms > max(self.floor, self.noise * self.ratio)))
        if voiced < self.min_voiced:
            self.noise = 0.95 * self.noise + 0.05 * float(np.median(rms))
        return voiced >= self.min_voiced
