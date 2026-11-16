"""Named configurations: the timing our product runs on, and the knobs tested on the benchmarks.

    from jev_interaction import preset
    cfg = preset("recommended", language="zh")

recommended the timing of the voice-call engine in our product, as it runs at scale today
            (paces, the floor asked 400 ms into an overlap, quiet-question marks up to 4 minutes, listening sounds up to 8 words)
tested      recommended plus the knobs measured in the README ("All knobs together"): a later floor question, short listening
            sounds, a "not said to me" choice, voices 10 dB under the caller treated as someone else's
default     the library defaults

Presets are timing only; providers are your choice (cookbook/stacks.md has the setups we recommend).
`production`, its earlier name, still works.
"""
from __future__ import annotations

from .config import Config

PRESETS: dict[str, dict] = {
    "default": {},
    "recommended": {
        "quiet_marks_s": (1.5, 4.0, 10.0, 25.0, 60.0, 120.0, 240.0),
        "listen_max_words": 8,
        "overlap_ask_ms": 400,
        "listen_gap_s": 3.0,
        "listen_finished_max": 0.65,
        "check_min_quiet_s": 10.0,
        "hangup_min_quiet_s": 25.0,
        "opening_turns": 2,
    },
}
PRESETS["production"] = PRESETS["recommended"]     # its earlier name
PRESETS["tested"] = {**PRESETS["recommended"], "overlap_ask_ms": 1000, "listen_max_words": 3, "not_for_me": True, "far_db": 10.0}


def preset(name: str = "recommended", **overrides) -> Config:
    """A Config from a named preset, with any field overridden."""
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose one of {sorted(set(PRESETS) - {'production'})}")
    return Config(**{**PRESETS[name], **overrides})


config = preset     # the 0.1.0 name
