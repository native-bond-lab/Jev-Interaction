"""Pluggable pieces. Each is a small protocol; swap any of them without touching the interaction layer.

    VAD          voice / no voice per frame          TenVAD (what our product runs), EnergyVAD (no extra package)
    Recognizer   closed segments of words            ScribeRealtime (ElevenLabs); any streaming ASR
    Responder    the agent's lines, streamed          OpenAICompatResponder (xAI, OpenAI, local servers)
    Synthesizer  audio for a line                     ElevenLabsTTS; any TTS
    Embedder     speaker embeddings (voiceprint)      EcapaEmbedder (speechbrain, optional); none: no voiceprint
Response latency is mostly the responder's first line: a faster model there makes the whole call faster, and the
interaction decisions do not change.
"""
from .base import VAD, Embedder, Recognizer, Responder, Segment, Synthesizer
from .energy_vad import EnergyVAD


def best_vad() -> VAD:
    """TEN VAD when the `ten-vad` package (and, on Linux, libc++) is there; the energy detector otherwise."""
    try:
        from .ten_vad import TenVAD
        return TenVAD()
    except Exception:  # noqa: BLE001 - not installed, or its native library would not load
        return EnergyVAD()


_EMBEDDER: list = []


def best_embedder() -> Embedder | None:
    """The process's ECAPA embedder when speechbrain is installed and JEV_VOICEPRINT is not 0, loading in the
    background; None otherwise (calls run without a voiceprint, as before)."""
    import importlib.util
    import os
    if os.getenv("JEV_VOICEPRINT", "1") == "0" or importlib.util.find_spec("speechbrain") is None:
        return None
    if not _EMBEDDER:
        from .ecapa import EcapaEmbedder
        _EMBEDDER.append(EcapaEmbedder())
        _EMBEDDER[0].warm()
    return _EMBEDDER[0]


__all__ = ["VAD", "Recognizer", "Responder", "Synthesizer", "Embedder", "Segment", "EnergyVAD", "best_vad", "best_embedder"]
