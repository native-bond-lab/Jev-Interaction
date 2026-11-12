"""Named configurations: the settings we run in production, and the knobs tested on the benchmarks.

    from jev_interaction.presets import config
    cfg = config("production", language="zh")

production  the timing of the companion-call engine this framework was extracted from, as it runs today
            (paces, 400 ms hold, quiet-question marks up to 4 minutes, listening sounds up to 8 words)
tested      production plus the knobs measured in the README ("All knobs together"): late hold, short listening
            sounds, a "not said to me" choice, voices 10 dB under the caller treated as someone else's
default     the library defaults

The providers that go with production are in .env.example (grok-4.3, ElevenLabs Scribe v2 realtime turbo, ElevenLabs
eleven_v4_turbo, jev-latest); the mainland-China providers are in .env.china.example.
"""
from __future__ import annotations

from .config import Config

PRESETS: dict[str, dict] = {
    "default": {},
    "production": {
        "quiet_marks_s": (1.5, 4.0, 10.0, 25.0, 60.0, 120.0, 240.0),
        "listen_max_words": 8,
        "hold_after_ms": 400,
        "hold_release_ms": 700,
        "listen_gap_s": 3.0,
        "listen_finished_max": 0.65,
        "check_min_quiet_s": 10.0,
        "hangup_min_quiet_s": 25.0,
        "opening_turns": 2,
    },
}
PRESETS["tested"] = {**PRESETS["production"], "hold_after_ms": 1000, "listen_max_words": 3, "not_for_me": True, "far_db": 10.0}


def config(name: str = "production", **overrides) -> Config:
    """A Config from a named preset, with any field overridden."""
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose one of {sorted(PRESETS)}")
    return Config(**{**PRESETS[name], **overrides})
