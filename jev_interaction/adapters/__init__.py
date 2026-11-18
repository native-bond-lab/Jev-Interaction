"""Pluggable pieces. Each is a small protocol; swap any of them without touching the interaction layer.

    VAD          voice / no voice per frame          TenVAD (what our product runs), EnergyVAD (no extra package)
    Recognizer   closed segments of words            ScribeRealtime (ElevenLabs); any streaming ASR
    Responder    the agent's lines, streamed          OpenAICompatResponder (xAI, OpenAI, local servers)
    Synthesizer  audio for a line                     ElevenLabsTTS; any TTS
    Embedder     speaker embeddings (voiceprint)      EcapaEmbedder (speechbrain, optional); none: no voiceprint
    Seer         a changed view as one sentence       OpenAISeer (any vision model, VISION_MODEL); none: no eyes
Response latency is mostly the responder's first line: a faster model there makes the whole call faster, and the
interaction decisions do not change.
"""
from .base import VAD, Embedder, Recognizer, Responder, Seer, Segment, Synthesizer
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


def best_seer() -> Seer | None:
    """Eyes for video calls when VISION_MODEL names a vision model (and JEV_VISION is not 0); None otherwise."""
    import os
    if os.getenv("JEV_VISION", "1") == "0" or not os.getenv("VISION_MODEL"):
        return None
    from .vision import OpenAISeer
    return OpenAISeer()


__all__ = ["VAD", "Recognizer", "Responder", "Synthesizer", "Embedder", "Seer", "Segment", "EnergyVAD", "best_vad",
           "best_embedder", "best_seer"]
