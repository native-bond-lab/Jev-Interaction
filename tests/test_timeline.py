"""The call's record is one timeline: turns with their times, what Jev answered and what was done with it, and one
account of "right now" for every question asked at the same instant."""
import asyncio
import json

import pytest

from jev_interaction import SamplePolicy
from jev_interaction.adapters.base import Segment
from jev_interaction.judge import state as S
from jev_interaction.ledger import Ledger, Turn
from jev_interaction.recorder import Recorder
from jev_interaction.testing import scripted_session
from jev_interaction.utterance import Utterance

TURN = {"done": {"finished": 0.9, "continuing": 0.1},
        "pace_patient": {"yes": 0.4, "no": 0.6},
        "listen": {"due": 0, "fits": 0, "quiet": 1.0, "answer_due": 0}}
FRAME = b"\x00" * 6400


class Clock:
    """time.monotonic for the session and its ledger, moved by hand (the event loop keeps the real one)."""
    def __init__(self, t: float):
        self.t = t

    def monotonic(self) -> float:
        return self.t


def timed_session(monkeypatch, answers, **kw):
    clock = Clock(1000.0)
    monkeypatch.setattr("jev_interaction.session.time", clock)
    monkeypatch.setattr("jev_interaction.ledger.time", clock)
    s, events, judge = scripted_session(answers, **kw)
    s.ledger.started = s.idle_since = clock.t

    async def hear(voice: bool, frames: int):
        for _ in range(frames):
            clock.t += 0.2
            s.vad.voice = voice
            await s.on_audio(FRAME)
    return s, events, judge, clock, hear


async def test_the_record_keeps_when_each_turn_began_and_ended_and_where_the_user_paused(monkeypatch):
    s, events, _, clock, hear = timed_session(monkeypatch, TURN, policies={"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    clock.t += 3.0
    await hear(True, 5)                                  # their voice from 3.2 s to 4.0 s into the call
    await s.on_segment(Segment("So I was thinking"))
    await hear(False, 4)                                 # 0.8 s with no voice, inside the turn
    await hear(True, 5)                                  # and it is back, to 5.8 s
    await s.on_segment(Segment("we could go on Friday."))
    await asyncio.sleep(0.05)
    await hear(False, 2)
    await s.tick()                                       # judged finished: answered at 6.2 s
    user, agent = s.ledger.turns
    assert (user.at, user.end) == (3.2, 5.8) and user.pauses == [(1, 0.8)]
    assert agent.at == 6.2 and agent.end is None         # her line is still going out
    await s.on_client({"type": "playback", "state": "playing"})
    clock.t += 2.0
    await s.on_client({"type": "playback", "state": "idle"})
    assert agent.end == 8.2

    clock.t += 1.5                                       # they start answering 1.7 s after the line ended
    await hear(True, 1)
    assert s.ledger.reply_gaps() == [pytest.approx(1.7)] and s.now().usual_reply_s is None   # one answer is not yet a habit
    assert any(e["type"] == "line" for e in events)


def test_how_soon_the_user_answers_is_read_off_the_record():
    led = Ledger(started=0.0)

    def said(text, end):
        t = led.agent(text)
        t.end = end
    said("How was it?", 10.0)
    led.turns.append(Turn("user", "fine", at=11.5, end=12.0))
    said("Just fine?", 15.0)
    led.turns.append(Turn("user", "mm", over=True, at=14.0, end=14.2))   # said over the line: not an answer to it
    led.turns.append(Turn("user", "", "[event]"))                        # the line she was given before speaking first
    said("Tell me more.", 20.0)
    led.turns.append(Turn("user", "well", at=22.5, end=23.0))
    led.turns.append(Turn("user", "and another thing", at=24.0, end=25.0))   # no line of hers before it: not an answer
    assert led.reply_gaps() == [1.5, 2.5]
    said("And then?", 30.0)
    led.open = Utterance(1, 33.0)                                        # the turn in progress counts
    assert led.reply_gaps() == [1.5, 2.5, 3.0]


async def test_every_question_asked_at_one_instant_reads_the_same_account_of_it():
    s, _, judge = scripted_session({**TURN, "spar": {"sparring": 0.0, "telling": 1.0}}, start_pace="eager")
    s.utt = Utterance(1, 0.0, speech_ms=2000)
    answer = judge.ask

    async def over_the_network(questions, state):                        # a judge takes a moment, so both questions are
        await asyncio.sleep(0.01)                                        # out before either answer is back
        return await answer(questions, state)
    judge.ask = over_the_network
    s.utt.segments.append((0.0, "and another thing about last night"))
    await asyncio.gather(s.ask("turn", utt_id=1), s.ask_cut_in(s.gen))   # two decisions asked at the same instant
    (asked_a, state_a), (asked_b, state_b) = judge.asked
    assert asked_a != asked_b and state_a["call"] == state_b["call"]     # the same text; each has the fields its facts point at
    assert "What the user has said so far" in state_a["call"] and state_b["user_words_so_far"] == "and another thing about last night"

    s.utt = None                                                         # nobody talking: the quiet question
    s.ledger.agent("So that was my week.")
    await s.ask_quiet(12.0)
    header = S.header(s.p, s.pace, s.ledger, s.cfg.judge_turns, s.cfg.judge_turn_chars)
    call = judge.asked[-1][1]["call"]                                    # the same text, beside the fields the facts point at
    assert call == header + S.now(s.now(quiet_s=12.0)) and "quiet for 12 s" in call


def test_now_says_which_of_the_four_moments_the_call_is_in():
    said = dict(user_open=True, segments=((58.0, "and then"),), heard="and then", speech_ms=900)
    assert S.now(S.Now("Mara", 60.0, False, "", silence_ms=400, **said)).startswith("Mara is silent.")
    assert 'Over it, for 0.9 s, the user is saying: "and then"' in S.now(S.Now("Mara", 60.0, True, "So there I was", **said))
    assert "It has been quiet for 7 s" in S.now(S.Now("Mara", 60.0, False, "So there I was.", quiet_s=7.0))
    assert "The user is listening" in S.now(S.Now("Mara", 60.0, True, "So there I was"))


async def test_what_jev_answered_and_what_was_done_with_it_are_in_the_record(tmp_path):
    log = tmp_path / "call.jsonl"
    s, _, _ = scripted_session(TURN, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    s.rec = Recorder(log)
    await s.on_segment(Segment("How was your day?"))
    await asyncio.sleep(0.05)
    s.silence_ms = 400
    await s.tick()
    kinds = [(n.kind, n.data.get("purpose") or n.data.get("what")) for n in s.ledger.notes]
    assert kinds == [("judge", "turn"), ("decision", "turn"), ("decision", "end_of_turn")]
    judged, chose, done = s.ledger.notes
    assert judged.data["answers"]["done"] == TURN["done"] and chose.data["action"] == "answer"
    assert done.data == {"what": "end_of_turn", "finished": 0.9, "go": True}
    assert [n.at for n in s.ledger.notes] == sorted(n.at for n in s.ledger.notes)

    await s.close()
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    asked = next(r for r in lines if r["event"] == "judge")
    assert asked["now"]["user_open"] and asked["now"]["heard"] == "How was your day?" and "at" in asked
    rows = lines[-1]["timeline"]                                         # turns and notes, in the order they happened
    assert [("turn" if "turn" in r else r["note"]) for r in rows] == ["turn", "judge", "decision", "decision", "turn"]
    assert rows[0]["turn"]["text"] == "How was your day?" and rows[4]["turn"]["role"] == "agent"


async def test_one_answer_from_jev_leads_to_one_thing_done_while_the_user_has_the_turn():
    """Taking the turn, cutting in and letting a sound slip in are one choice: judged finished, the agent waits for
    their voice to stop and puts nothing in; not finished, it may cut in (a pace that does); else a sound; else nothing."""
    async def after(done, listen, cut=None, pace="normal", speech_ms=2000):
        answers = {"done": {"finished": done, "continuing": 1 - done}, "listen": listen}
        if cut is not None:
            answers["spar"] = {"sparring": cut, "telling": 1 - cut}
        s, events, judge = scripted_session(answers, start_pace=pace)
        s.utt = Utterance(1, 0.0, speech_ms=speech_ms)
        await s.on_segment(Segment("and then the vase went over,"))
        await asyncio.sleep(0.05)
        chose = [n.data for n in s.ledger.notes if n.data.get("what") == "turn"]
        assert len(judge.asked) == 1 and len(chose) == 1               # one request, one choice
        return chose[0]["action"], judge.asked[0][0], [e["type"] for e in events if e["type"] in ("line", "listen")]
    sound, silent = {"due": 0.0, "fits": 0.9, "quiet": 0.1}, {"due": 0.0, "fits": 0.1, "quiet": 0.9}
    assert (await after(0.9, sound))[::2] == ("answer", [])              # finished: no sound first, the reply comes on the tick
    assert (await after(0.2, sound))[::2] == ("listen", ["listen"])
    assert (await after(0.2, silent))[::2] == ("nothing", [])
    act, asked, said = await after(0.2, sound, cut=0.9, pace="eager")
    assert act == "cut_in" and "spar" in asked and "listen" not in said and "line" in said    # she cuts in: no "mm" beside it
    assert (await after(0.9, sound, cut=0.9, pace="eager"))[0] == "answer"                   # they finished: nothing to cut into
    assert "spar" not in (await after(0.2, sound, pace="eager", speech_ms=600))[1]            # too little said to cut into
    assert "spar" not in (await after(0.2, sound))[1]                                         # a pace that does not cut in
