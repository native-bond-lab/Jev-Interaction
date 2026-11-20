"""Pluggable pieces. Each is a small protocol; swap any of them without touching the interaction layer.

    VAD          voice / no voice per frame          TenVAD (what our product runs), EnergyVAD (no extra package)
    Recognizer   closed segments of words            ScribeRealtime (ElevenLabs); any streaming ASR
    Responder    the agent's lines, streamed          OpenAICompatResponder (xAI, OpenAI, local servers)
    Synthesizer  audio for a line                     ElevenLabsTTS; any TTS
    SoundModel   "finished?" from the voice alone     SmartTurn v3.2 (onnxruntime, optional); none: the words alone
    Embedder     speaker embeddings (voiceprint)      EcapaEmbedder (speechbrain, optional); none: no voiceprint
Response latency is mostly the responder's first line: a faster model there makes the whole call faster, and the
interaction decisions do not change.
"""
from .base import VAD, Embedder, Recognizer, Responder, Segment, SoundModel, Synthesizer
from .energy_vad import EnergyVAD


def best_vad() -> VAD:
    """TEN VAD when the `ten-vad` package (and, on Linux, libc++) is there; the energy detector otherwise."""
    try:
        from .ten_vad import TenVAD
        return TenVAD()
    except Exception:  # noqa: BLE001 - not installed, or its native library would not load
        return EnergyVAD()


_LOCAL: dict = {}


def _local(kind: str):
    """The process's model for an optional node (registry.OPTIONAL): the provider its setting names, built once and
    warmed in the background; None when the node is off or its package is not installed."""
    import logging

    from . import registry
    name = registry.selected(kind)
    if not name:
        return None
    if (kind, name) not in _LOCAL:
        try:
            model = registry.create(kind, name)
        except Exception as exc:  # noqa: BLE001 - a plugin that fails to build must not stop the server
            logging.getLogger(__name__).warning("%s %r not available: %s", kind, name, exc)
            model = None
        if model is not None:
            model.warm()
        _LOCAL[(kind, name)] = model
    return _LOCAL[(kind, name)]


def best_embedder() -> Embedder | None:
    """Speaker embeddings for the caller's voiceprint: JEV_VOICEPRINT names the provider (ecapa, built in, when
    speechbrain is installed; or one you register as "voiceprint"); "0" turns it off. None: no voiceprint."""
    return _local("voiceprint")


def best_sound() -> SoundModel | None:
    """"Have they finished" from the sound of the voice: JEV_SOUND names the provider (smart-turn, built in, when
    onnxruntime is installed; or one you register as "sound"); "off" turns it off. None: the turn goes by the words."""
    return _local("sound")


__all__ = ["VAD", "Recognizer", "Responder", "Synthesizer", "Embedder", "SoundModel", "Segment", "EnergyVAD", "best_vad",
           "best_embedder", "best_sound"]
