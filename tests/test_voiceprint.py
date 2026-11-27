"""The caller's voiceprint: built from the answered words, a clear stranger is not answered, doubt changes nothing."""
import asyncio

import numpy as np
import pytest

from jev_interaction.testing import FakeEmbedder, scripted_session
from jev_interaction.voiceprint import Voiceprint

FRAME = 6400                                    # 200 ms of 16 kHz PCM16


def unit(i: int) -> np.ndarray:
    v = np.zeros(8, dtype=np.float32)
    v[i] = 1.0
    return v


def test_a_stranger_needs_a_print_of_two_and_a_long_enough_clip():
    vp = Voiceprint()
    vp.add(1, unit(0), -20.0)
    assert vp.judge(unit(3), -20.0, 3000)["label"] == "unknown"        # one sample: never someone else
    vp.add(2, unit(0), -20.0)
    assert vp.judge(unit(0), -20.0, 3000)["label"] == "caller"
    assert vp.judge(unit(3), -20.0, 1000)["label"] == "unknown"        # too short to call
    assert vp.judge(unit(3), -20.0, 3000)["label"] == "other"
    doubtful = (unit(0) * 0.35 + unit(3)) / np.linalg.norm(unit(0) * 0.35 + unit(3))
    assert vp.judge(doubtful, -20.0, 3000)["label"] == "unknown"       # in between, at the caller's loudness
    assert vp.judge(doubtful, -40.0, 3000)["label"] == "other"         # in between and far from the microphone


async def speak(s, voice: int, ms: int):
    s.vad.voice = True
    for _ in range(ms // 200):
        await s.on_audio(bytes([voice]) * FRAME)
    await asyncio.gather(*[t for t in list(s._tasks) if "judge_voice" in repr(t.get_coro())])
    s.vad.voice = False


async def settle(s):
    while s._tasks:
        await asyncio.gather(*list(s._tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_the_caller_is_learned_from_answered_words_and_a_stranger_is_not_answered():
    s, events, _ = scripted_session(embedder=FakeEmbedder())
    for voice in (1, 2):                                               # the caller, twice, answered
        await speak(s, voice, 2400)
        await s._enroll(s.utt)
        s.utt = None
    assert len(s.voiceprint.entries) == 2
    await speak(s, 1, 2000)
    assert s.utt.who["label"] == "caller" and s._someone_else() is None
    await settle(s)
    caller_asides = len(s.llm.seen)
    assert caller_asides == 1
    s.utt = None
    await speak(s, 5, 2000)                                            # someone else in the room
    assert s.utt.who["label"] == "other" and s._someone_else() == "voice"
    await settle(s)
    from jev_interaction.decisions.turn import TURN
    await TURN.answer(s)
    assert any(e["type"] == "decision" and e.get("what") == "not_for_me" and e.get("why") == "voice" for e in events)
    assert s.utt is None and len(s.llm.seen) == caller_asides           # the stranger gets no reply or aside


@pytest.mark.asyncio
async def test_without_an_embedder_nothing_changes():
    s, _, _ = scripted_session()
    await speak(s, 5, 2000)
    assert s.utt.who is None and not s.utt.audio and s._someone_else() is None
