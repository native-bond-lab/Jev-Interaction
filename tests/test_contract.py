"""The public surface (docs/stability.md). Changing it is allowed, but on purpose: edit the list here, say it in the
CHANGELOG, and keep the old name working with a warning when one is renamed."""
import dataclasses
import inspect
import pathlib
import re

import jev_interaction
from jev_interaction import Config, Pace, Session
from jev_interaction.adapters import base

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPORTS = {"Session", "Profile", "Config", "Pace", "preset", "PRESETS", "JevClient", "Recorder", "Decision", "DECISIONS",
           "register", "Policy", "SamplePolicy", "ThresholdPolicy", "ArgmaxPolicy"}
SESSION_ARGS = ["profile", "send", "judge", "recognizer", "responder", "vad", "config", "recorder", "system_template",
                "speech", "cast", "embedder"]
CONFIG_FIELDS = {"language", "frame_ms", "sample_rate", "paces", "start_pace", "opening_turns", "policies", "voice_min_ms",
                 "overlap_ask_ms", "sound_close_ms", "listen_gap_s", "listen_min_gap_s", "listen_due_min", "turn_reask_ms",
                 "turn_last_ms", "listen_finished_max", "quiet_marks_s", "quiet_jitter", "check_min_quiet_s",
                 "hangup_min_quiet_s", "judge_timeout_s", "judge_turns", "judge_turn_chars", "safe_words",
                 "listen_max_words", "voice_same", "voice_other", "voice_verdict_ms", "voice_enroll_ms", "not_for_me",
                 "far_db", "hold_after_ms", "hold_release_ms"}
PACE_FIELDS = {"name", "description", "max_wait_ms", "yield_p", "leads", "cut_in"}
PROTOCOLS = {"VAD": {"is_voice"}, "Recognizer": {"connect", "send", "segments", "close"}, "Responder": {"lines"},
             "Synthesizer": {"audio"}, "Embedder": {"ready", "warm", "embed"}}
POLICIES = {"end_of_turn", "listen", "floor", "cut_in", "quiet", "who"}
CLIENT_MESSAGES = {"start", "playback", "heard"}
SERVER_EVENTS = {"line", "listen", "user", "stop", "finish_line", "decision", "persona", "pace", "error", "queue", "ready",
                 "busy", "hangup"}


def test_python_surface():
    assert set(jev_interaction.__all__) == EXPORTS
    assert list(inspect.signature(Session.__init__).parameters)[1:] == SESSION_ARGS
    assert {f.name for f in dataclasses.fields(Config)} == CONFIG_FIELDS
    assert {f.name for f in dataclasses.fields(Pace)} == PACE_FIELDS
    assert set(Config().policies) == POLICIES
    assert {"recommended", "tested", "default"} <= set(jev_interaction.PRESETS)
    for name, methods in PROTOCOLS.items():
        assert methods <= set(dir(getattr(base, name))), name


def test_the_events_the_code_sends_are_the_documented_ones():
    code = "".join(p.read_text(encoding="utf-8") for p in [ROOT / "jev_interaction/session.py",
                                                           ROOT / "jev_interaction/server/app.py",
                                                           *(ROOT / "jev_interaction/decisions").glob("*.py")])
    sent = set(re.findall(r'send\(type="([a-z_]+)"', code)) | set(re.findall(r'\{"type": "([a-z_]+)"', code)) - {"start"}
    read = set(re.findall(r'msg\.get\("type"\) == "([a-z_]+)"', code)) | {"start"}
    doc = (ROOT / "docs/protocol.md").read_text(encoding="utf-8")
    documented = set(re.findall(r'^\| `([a-z_]+)` \|', doc, re.M))
    assert sent == SERVER_EVENTS and sent <= documented, (sent ^ SERVER_EVENTS, sent - documented)
    assert read == CLIENT_MESSAGES and all(f'"type": "{m}"' in doc for m in read)
