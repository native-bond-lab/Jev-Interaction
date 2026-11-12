"""Pluggable pieces. Each is a small protocol; swap any of them without touching the interaction layer.

    VAD          voice / no voice per frame          TenVAD (what production runs), EnergyVAD (no extra package)
    Recognizer   closed segments of words            ScribeRealtime (ElevenLabs); any streaming ASR
    Responder    the agent's lines, streamed          OpenAICompatResponder (xAI, OpenAI, local servers)
    Synthesizer  audio for a line                     ElevenLabsTTS; any TTS
Response latency is mostly the responder's first line: a faster model there makes the whole call faster, and the
interaction decisions do not change.
"""
from .base import VAD, Recognizer, Responder, Segment, Synthesizer
from .energy_vad import EnergyVAD


def best_vad() -> VAD:
    """TEN VAD when the `ten-vad` package (and, on Linux, libc++) is there; the energy detector otherwise."""
    try:
        from .ten_vad import TenVAD
        return TenVAD()
    except Exception:  # noqa: BLE001 - not installed, or its native library would not load
        return EnergyVAD()


__all__ = ["VAD", "Recognizer", "Responder", "Synthesizer", "Segment", "EnergyVAD", "best_vad"]
