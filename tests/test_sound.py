"""The sound of the voice as a second opinion on "have they finished" (Config.sound_rule, adapters/smart_turn.py)."""
import asyncio
import time

import numpy as np

from jev_interaction.adapters.base import Segment
from jev_interaction.adapters.smart_turn import features
from jev_interaction.decisions.turn import TURN as TURN_DECISION
from jev_interaction.policy import ThresholdPolicy
from jev_interaction.testing import FakeSound, scripted_session

DONE = lambda p: {"done": {"finished": p, "continuing": 1 - p},           # noqa: E731
                  "listen": {"due": 0, "fits": 0, "quiet": 1.0, "answer_due": 0}}


async def judged(p_words: float, p_sound: float | None, **cfg):
    sound = FakeSound(p_sound)
    s, events, judge = scripted_session(DONE(p_words), policies={"end_of_turn": ThresholdPolicy(default=0.5)}, sound=sound, **cfg)
    await s.on_segment(Segment("I think that's all for today."))
    await asyncio.sleep(0.05)
    s.vad.voice = False
    await s.on_audio(b"\x00" * 6400)                 # a frame of quiet: the sound model reads the pause
    await asyncio.sleep(0.05)
    return s, events, sound


def lines(events):
    return [e for e in events if e["type"] == "line"]


async def test_and_the_turn_waits_for_the_sound_when_the_words_say_finished():
    s, events, sound = await judged(0.9, 0.2)        # words sure, the voice says they will go on (en line 0.4)
    assert sound.heard and s.sound_p() == 0.2
    assert not await TURN_DECISION.on_tick(s, time.monotonic()) and not lines(events)
    held = [n for n in s.ledger.notes if n.kind == "decision" and n.data.get("go") == "held"]
    assert len(held) == 1 and held[0].data["sound"] == 0.2
    sound.p = 0.7                                    # the next frame of quiet sounds finished: both agree
    await s.on_audio(b"\x00" * 6400)
    await asyncio.sleep(0.05)
    assert await TURN_DECISION.on_tick(s, time.monotonic()) and lines(events)
    decision = next(e for e in events if e.get("what") == "end_of_turn")
    assert decision["by"] == "both" and decision["sound"] == 0.7
    assert [n.data["p"] for n in s.ledger.notes if n.kind == "judge" and n.data.get("purpose") == "sound"] == [0.2, 0.7]


async def test_and_words_judged_finished_are_answered_after_a_while_however_the_voice_sounds():
    s, events, _ = await judged(0.9, 0.1)
    s.silence_ms = s.cfg.sound_wait_ms
    assert await TURN_DECISION.on_tick(s, time.monotonic())
    assert next(e for e in events if e.get("what") == "end_of_turn")["by"] == "waited"


async def test_and_a_finished_sound_alone_does_not_take_the_turn():
    s, events, _ = await judged(0.6, 0.95)           # under the words' own line (Config.words_min 0.8)
    assert not await TURN_DECISION.on_tick(s, time.monotonic()) and not lines(events)
    asked = len(s.judge.asked)
    s.silence_ms = s.cfg.turn_reask_ms[0]            # the quiet grows: Jev is asked again
    await TURN_DECISION.on_tick(s, time.monotonic())
    await asyncio.sleep(0.05)
    assert len(s.judge.asked) == asked + 1


async def test_or_either_one_takes_the_turn():
    s, events, _ = await judged(0.3, 0.95, sound_rule="or")
    assert await TURN_DECISION.on_tick(s, time.monotonic())
    assert next(e for e in events if e.get("what") == "end_of_turn")["by"] == "sound"


async def test_the_sound_line_is_the_languages_own():
    s, _, _ = await judged(0.9, 0.6, language="zh")  # 0.6 is finished for English, not for Chinese (line 0.8)
    assert s.cfg.sound_line() == 0.8
    assert not await TURN_DECISION.on_tick(s, time.monotonic())


async def test_off_or_not_ready_goes_by_the_words_as_before():
    for kw, p in (({"sound_rule": "off"}, 0.0), ({}, None)):
        s, events, _ = await judged(0.9, p, **kw)
        assert await TURN_DECISION.on_tick(s, time.monotonic()) and lines(events)
        assert "by" not in next(e for e in events if e.get("what") == "end_of_turn")


async def test_a_reading_from_before_the_voice_came_back_is_dropped():
    s, _, _ = await judged(0.9, 0.7)
    s.vad.voice = True
    await s.on_audio(b"\x01" * 6400)                 # they go on: the reading of the pause no longer holds
    assert s.sound_p() is None


def test_the_model_input_is_whispers_log_mel_of_the_last_8_seconds():
    x = features(np.sin(np.linspace(0, 2000, 20 * 16000)).astype(np.float32))    # 20 s in: only the last 8 count
    assert x.shape == (1, 80, 800) and x.dtype == np.float32 and np.isfinite(x).all()
    assert features(np.zeros(100, dtype=np.float32)).shape == (1, 80, 800)       # short audio is padded with silence


def test_a_sound_model_or_voiceprint_of_your_own_plugs_in_through_the_registry(monkeypatch):
    from jev_interaction import adapters as A
    from jev_interaction.adapters import registry as R
    from jev_interaction.testing import FakeEmbedder, FakeSound
    mine = FakeSound(0.9)
    R.register("sound", "mine", lambda **_: mine, label="My sound model")
    R.register("voiceprint", "mine", lambda **_: FakeEmbedder(), label="My voiceprint")
    try:
        monkeypatch.setattr(A, "_LOCAL", {})
        monkeypatch.setenv("JEV_SOUND", "mine")
        monkeypatch.setenv("JEV_VOICEPRINT", "mine")
        assert A.best_sound() is mine and A.best_sound() is mine            # built once per process
        assert isinstance(A.best_embedder(), FakeEmbedder)
        monkeypatch.setenv("JEV_SOUND", "off")
        monkeypatch.setenv("JEV_VOICEPRINT", "0")
        assert A.best_sound() is None and A.best_embedder() is None
        monkeypatch.setenv("JEV_SOUND", "on")
        assert R.selected("sound") == "smart-turn" and R.selected("voiceprint") is None
        assert "JEV_SOUND" not in R.missing_settings()                      # optional: never a setup step
    finally:
        R._PROVIDERS.pop(("sound", "mine"))
        R._PROVIDERS.pop(("voiceprint", "mine"))
