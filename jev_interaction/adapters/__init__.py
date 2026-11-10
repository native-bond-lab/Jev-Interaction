"""Pluggable pieces. Each is a small protocol; swap any of them without touching the interaction layer.

    VAD          voice / no voice per frame          EnergyVAD (built in); TEN VAD or Silero fit the same protocol
    Recognizer   closed segments of words            ScribeRealtime (ElevenLabs); any streaming ASR
    Responder    the agent's lines, streamed          OpenAICompatResponder (xAI, OpenAI, local servers)
    Synthesizer  audio for a line                     ElevenLabsTTS; any TTS
Response latency is mostly the responder's first line: a faster model there makes the whole call faster, and the
interaction decisions do not change.
"""
from .base import VAD, Recognizer, Responder, Synthesizer, Segment
from .energy_vad import EnergyVAD

__all__ = ["VAD", "Recognizer", "Responder", "Synthesizer", "Segment", "EnergyVAD"]
