"""Who is talking: the caller's voiceprint, built from the call itself.

On a speakerphone in a busy room most of what reaches the recognizer can be other people, and the agent's own voice
coming back. Each stretch of the user's voice gets a speaker embedding (an `Embedder`, e.g. ECAPA-TDNN on the CPU) and
is compared with the caller's voiceprint. The print starts empty; the first words the agent answers become it, and every
later answered match is averaged in, so the check grows surer as the call goes on. Loudness is the second cue: the
caller's mouth is at the microphone, the room is not.

The verdict is evidence, not a switch: a clear stranger is not answered and does not stop the agent's line; a doubtful
voice is treated as before. A thin print or a short clip can say "caller", never "someone else".
"""
from __future__ import annotations

import numpy as np

ENROLL_MAX = 12              # embeddings kept for the print (the oldest drop out)
MIN_ENROLL = 2               # entries the print needs before any voice can be called someone else (one short sample
                             # once made the caller a stranger for the rest of a call)


class Voiceprint:
    """The caller's voice as the call has heard it: a running mean of unit embeddings and how loud they speak."""

    def __init__(self, same: float = 0.45, other: float = 0.25, far_db: float = 10.0, verdict_ms: int = 1500):
        self.same, self.other, self.far_db, self.verdict_ms = same, other, far_db, verdict_ms
        self.entries: list[tuple[int, np.ndarray, float | None]] = []   # (utterance id, embedding, level dB)
        self.mean: np.ndarray | None = None
        self.level: float | None = None

    def add(self, uid: int, emb: np.ndarray, level: float | None) -> None:
        self.entries = ([e for e in self.entries if e[0] != uid] + [(uid, emb, level)])[-ENROLL_MAX:]
        m = np.mean([e[1] for e in self.entries], axis=0)
        n = float(np.linalg.norm(m))
        self.mean = m / n if n > 0 else None
        levels = [e[2] for e in self.entries if e[2] is not None]
        self.level = float(np.median(levels)) if levels else None

    def judge(self, emb: np.ndarray | None, level: float | None, audio_ms: int) -> dict:
        """label caller | other | unknown, with the numbers behind it. A quiet voice that does not match well is the
        room, not the caller."""
        sim = None if self.mean is None or emb is None else float(np.dot(self.mean, emb))
        far = self.level is not None and level is not None and level < self.level - self.far_db
        sure_enough = len(self.entries) >= MIN_ENROLL and audio_ms >= self.verdict_ms
        if sim is None:
            label = "unknown"
        elif sim >= self.same:
            label = "caller"
        elif sure_enough and (sim <= self.other or (far and sim < (self.same + self.other) / 2)):
            label = "other"
        else:
            label = "unknown"
        return {"label": label, "sim": None if sim is None else round(sim, 3), "far": bool(far), "n": len(self.entries)}
