"""Video calls: a picture the page took when the view changed becomes one sentence in the record, and Jev decides
whether the agent says something about it once the line is free."""
import asyncio
import base64

import pytest

from jev_interaction.testing import FakeSeer, scripted_session

PIC = base64.b64encode(b"\xff\xd8 a picture").decode()


async def settle(s):
    while s._tasks - {t for t in s._tasks if "_loop" in repr(t.get_coro())}:
        await asyncio.gather(*[t for t in list(s._tasks) if "_loop" not in repr(t.get_coro())])


@pytest.mark.asyncio
async def test_a_change_goes_into_the_record_and_jev_says_remark():
    seer = FakeSeer("the user holds up a red mug")
    s, events, judge = scripted_session({"notice": {"remark": 0.8, "let_be": 0.2}}, seer=seer)
    await s.on_client({"type": "frame", "image": PIC, "change": 0.2})
    await settle(s)
    assert any(e["type"] == "seen" and e["text"] == "the user holds up a red mug" for e in events)
    await s.tick()
    await settle(s)
    asked = [state for qs, state in judge.asked if "notice" in qs]
    assert asked and "red mug" in asked[0]
    assert any(e.get("what") == "notice" and e["action"] == "remark" for e in events)
    said = s.llm.seen[-1]
    assert any("(you see: the user holds up a red mug)" in m["content"] for m in said if m["role"] == "user")
    assert any(e["type"] == "line" for e in events)


@pytest.mark.asyncio
async def test_let_be_says_nothing_and_a_failed_judge_says_nothing():
    for answers in ({"notice": {"remark": 0.3, "let_be": 0.7}}, {}):
        s, events, _ = scripted_session(answers, seer=FakeSeer("the user scratches their head"))
        await s.on_client({"type": "frame", "image": PIC, "change": 0.15})
        await settle(s)
        await s.tick()
        await settle(s)
        assert not any(e["type"] == "line" for e in events)
        assert s.ledger.turns[-1].role == "seen"           # it stays in the record: the next reply knows it


@pytest.mark.asyncio
async def test_the_first_look_is_the_scene_not_a_change():
    s, events, judge = scripted_session({"notice": {"remark": 1.0}}, seer=FakeSeer("a person at a desk"))
    await s.on_client({"type": "frame", "image": PIC, "first": True})
    await settle(s)
    await s.tick()
    await settle(s)
    assert s.sight == "a person at a desk" and s.sight_pending is None
    assert not any("notice" in qs for qs, _ in judge.asked)


@pytest.mark.asyncio
async def test_a_sight_waits_while_the_user_talks_and_passes_when_stale():
    s, events, judge = scripted_session({"notice": {"remark": 1.0}}, seer=FakeSeer("the user stands up"), notice_stale_s=0.0)
    s._open_utterance()
    await s.on_client({"type": "frame", "image": PIC, "change": 0.3})
    await settle(s)
    await s.tick()                                      # the user is talking: nothing asked
    assert not any("notice" in qs for qs, _ in judge.asked)
    s.utt = None
    await asyncio.sleep(0.01)
    await s.tick()                                      # free now, but too late
    await settle(s)
    assert not any("notice" in qs for qs, _ in judge.asked) and s.sight_pending is None
    assert any(t.role == "seen" for t in s.ledger.turns)


@pytest.mark.asyncio
async def test_nothing_new_bad_pictures_and_no_eyes_change_nothing():
    s, events, _ = scripted_session(seer=FakeSeer(""))
    await s.on_client({"type": "frame", "image": PIC})
    await s.on_client({"type": "frame", "image": "not base64!"})
    await settle(s)
    assert not s.ledger.turns and not any(e["type"] == "seen" for e in events)
    s2, events2, _ = scripted_session()
    await s2.on_client({"type": "frame", "image": PIC})
    assert not s2._tasks and not events2


@pytest.mark.asyncio
async def test_a_sight_is_not_a_turn_and_jev_reads_it():
    s, _, _ = scripted_session(seer=FakeSeer("the user pours tea"))
    s.ledger.agent("Hi there.")
    await s.see(b"x")
    assert s.ledger.last_is_agent()
    assert "Seen on video: the user pours tea" in s.ledger.recent_text("Mara", 8, 300)
