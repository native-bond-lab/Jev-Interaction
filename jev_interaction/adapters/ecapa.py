"""ECAPA-TDNN speaker embeddings (speechbrain, CPU, ~100 ms a clip): the voiceprint the call engine in our product runs.

    pip install "jev-interaction[voiceprint]"       # speechbrain + torch

The model (about 80 MB) is downloaded from Hugging Face on first use into JEV_VOICEPRINT_CACHE and loaded in a
background thread; until it is ready, or without the packages, `ready` is False and every check says "unknown".
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading

import numpy as np

log = logging.getLogger(__name__)
MODEL = os.getenv("JEV_VOICEPRINT_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
MIN_MS = 800                 # shorter clips give unstable embeddings
WINDOW_MS = 4000             # the last 4 s of a clip are embedded: a long clip mixes voices and costs more


class EcapaEmbedder:
    def __init__(self, model: str = MODEL, cache: str | None = None):
        self.model_id = model
        self.cache = cache or os.getenv("JEV_VOICEPRINT_CACHE") or str(pathlib.Path.home() / ".cache" / "jev-interaction" / "voiceprint")
        self.model = None
        self.error = ""
        self._lock = threading.Lock()
        self._started = False

    def warm(self) -> None:
        """Start loading the model off the request path (once)."""
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._load, name="voiceprint-model", daemon=True).start()

    def _load(self) -> None:
        try:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier
            torch.set_num_threads(max(1, min(2, os.cpu_count() or 1)))
            self.model = EncoderClassifier.from_hparams(source=self.model_id, savedir=self.cache, run_opts={"device": "cpu"})
            log.info("voiceprint model ready: %s", self.model_id)
        except Exception as exc:  # noqa: BLE001 - calls run without the check
            self.error = f"{type(exc).__name__}: {str(exc)[:120]}"
            log.warning("voiceprint model unavailable: %s", self.error)

    @property
    def ready(self) -> bool:
        return self.model is not None

    def embed(self, pcm: bytes) -> np.ndarray | None:
        """A unit-length embedding of 16 kHz PCM16, or None when the model is not ready or the clip is too short."""
        if self.model is None or len(pcm) < MIN_MS * 32:
            return None
        import torch
        x = torch.from_numpy(np.frombuffer(pcm[-WINDOW_MS * 32:], dtype=np.int16).astype(np.float32) / 32768).unsqueeze(0)
        with torch.no_grad():
            emb = self.model.encode_batch(x).squeeze().cpu().numpy().astype(np.float32)
        n = float(np.linalg.norm(emb))
        return emb / n if n > 0 else None
