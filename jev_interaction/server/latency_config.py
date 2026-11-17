"""Safe configuration identity for comparing calls; no keys, paths, query strings or conversation text."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from ..adapters import registry


def snapshot():
    host = urlparse(os.getenv("LLM_BASE_URL", "")).hostname or ""
    asr, tts = registry.selected("asr"), registry.selected("tts")
    asr_model = (os.getenv("ELEVENLABS_ASR_MODEL", "scribe_v3_live") if asr == "elevenlabs" else
                 os.getenv("DOUBAO_ASR_RESOURCE_ID") if asr == "doubao" else None)
    tts_model = (os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo") if tts == "elevenlabs" else
                 os.getenv("DOUBAO_TTS_RESOURCE_ID") if tts == "doubao" else None)
    reuse = os.getenv("ELEVENLABS_TTS_REUSE_CONNECTION", "1") != "0" if tts == "elevenlabs" else None
    return {"schema": 1, "llm_host": host, "llm_model": os.getenv("LLM_MODEL", ""), "asr": asr, "tts": tts,
            "judge_host": urlparse(os.getenv("JEV_URL", "https://api.typesafe.ai/v1/systemone")).hostname or "",
            "judge_model": os.getenv("JEV_MODEL", "jev-latest"),
            "asr_model": asr_model, "tts_model": tts_model,
            "chunk_mode": os.getenv("LLM_CHUNK_MODE", "newline"),
            "llm_reuse": os.getenv("LLM_REUSE_CONNECTION", "1") != "0",
            "tts_prefetch": os.getenv("TTS_PREFETCH", "1") != "0",
            "tts_chunk_bytes": os.getenv("ELEVENLABS_TTS_CHUNK_BYTES", "0") if tts == "elevenlabs" else None,
            "tts_reuse": reuse,
            "tts_prewarm": bool(reuse and os.getenv("ELEVENLABS_TTS_PREWARM", "1") != "0") if tts == "elevenlabs" else None,
            "preset": os.getenv("JEV_PRESET", "recommended")}
