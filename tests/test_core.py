import asyncio
import time

import pytest

from jev_interaction import ArgmaxPolicy, Config, Profile, SamplePolicy, ThresholdPolicy
from jev_interaction.adapters.base import Segment
from jev_interaction.judge import questions as Q
from jev_interaction.session import Session


def test_policies():
    p = {"a": 0.2, "b": 0.7, "c": 0.1}
    assert ArgmaxPolicy().choose(p) == "b"
    assert SamplePolicy(rng=lambda: 0.1).choose(p) == "a"
    assert SamplePolicy(rng=lambda: 0.95).choose(p) == "c"
    assert SamplePolicy(rng=lambda: 0.95).choose(p, allowed=["a", "b"]) == "b"        # renormalised over what is allowed
    assert ThresholdPolicy({"b": 0.8}, fallback="a").choose(p) == "a"
    assert ThresholdPolicy({"b": 0.6}).choose(p) == "b"
    assert SamplePolicy(rng=lambda: 0.3).draw(0.4) and not SamplePolicy(rng=lambda: 0.5).draw(0.4)


def test_profile_reaches_the_judge_header():
    p = Profile("Elias Brandt", task="An archivist who keeps a caller company.", manner="Listens in complete silence.")
    assert p.short == "Elias"
    assert "On the call: Listens in complete silence." in p.judge_header()


def test_questions_offer_choices_by_pace():
    c = Q.floor_criteria("Mara", finish=True, overrule=False, aside=False, jump=True)
    assert set(c) == {"carry_on", "yield", "finish_first", "jump_in"}
    assert set(Q.listen("Mara")["criteria"]) == {"continuer", "feeling", "echo", "quiet", "answer_due"}


class FakeJudge:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    async def ask(self, questions, state):
        self.asked.append((set(questions), state))
        return {k: {"choice": max(v, key=v.get), "probabilities": v} for k, v in self.answers.items() if k in questions}


class FakeASR:
    def __init__(self):
        self.q = asyncio.Queue()

    async def connect(self): ...
    async def send(self, pcm): ...
    async def close(self): ...

    async def segments(self):
        while (s := await self.q.get()) is not None:
            yield s


class FakeLLM:
    def __init__(self, lines=("Hey.", "What's up?")):
        self.seen, self.out = [], lines

    async def lines(self, messages, max_tokens=160):
        self.seen.append(messages)
        for x in self.out:
            yield x


class FakeVAD:
    def __init__(self):
        self.voice = False

    def is_voice(self, pcm):
        return self.voice


def make(answers, policies=None):
    events = []

    async def send(e):
        events.append(e)
    cfg = Config(policies={**Config().policies, **(policies or {})}, opening_turns=0)
    judge = FakeJudge(answers)
    s = Session(Profile("Mara Quinn", task="A companion who chats.", manner="Chatty listener."), send=send, judge=judge,
                recognizer=FakeASR(), responder=FakeLLM(), vad=FakeVAD(), config=cfg)
    return s, events, judge


TURN = {"done": {"finished": 0.9, "continuing": 0.1}, "wait": {"now": 1.0, "half_second": 0, "two_seconds": 0, "hold": 0},
        "kind": {"reply": 0.9, "sound": 0.1}, "pace": {"normal": 0.6, "patient": 0.4, "narrate": 0, "eager": 0},
        "listen": {"continuer": 0, "feeling": 0, "echo": 0, "quiet": 1.0, "answer_due": 0}}


async def test_a_finished_turn_is_answered_and_the_pace_timing_is_blended():
    s, events, judge = make(TURN, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    await s.on_segment(Segment("How was your day?"))
    await asyncio.sleep(0.05)
    assert "Chatty listener." in judge.asked[0][1]                      # the persona's manner is in every state
    s.silence_ms = 400
    await s.tick()
    assert any(e["type"] == "line" and e["text"] == "Hey." for e in events)
    assert s.ledger.turns[0].text == "How was your day?" and "event: they spoke" in s.ledger.turns[0].data_line
    assert s.params().max_wait_ms == int(0.6 * 1200 + 0.4 * 2500)


async def test_talking_over_the_agent_holds_then_the_floor_question_decides():
    s, events, _ = make({"floor": {"carry_on": 0.1, "yield": 0.8, "finish_first": 0.1, "jump_in": 0.0}})
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    s.vad.voice = True
    for _ in range(3):
        await s.on_audio(b"\x00" * 6400)
    assert any(e["type"] == "hold" for e in events)
    await s.on_segment(Segment("Wait, can I ask something?"))
    await asyncio.sleep(0.05)
    assert any(e["type"] == "stop" for e in events)
    assert s.ledger.last_agent().cut


async def test_a_quiet_line_may_be_picked_up_and_hang_up_is_never_first():
    s, events, _ = make({"quiet": {"go_on": 0.0, "check": 0.0, "wait": 0.0, "hang_up": 1.0}}, {"quiet": ArgmaxPolicy()})
    s.ledger.agent("That's my story.")
    await s.ask_quiet(30.0)
    assert not any(e["type"] == "line" for e in events)                  # hang-up not allowed before anything was said into it
    s.spoke_into_quiet = 1
    await s.ask_quiet(30.0)
    assert any(e["type"] == "line" for e in events) and s.hanging_up


def test_a_profile_brings_its_own_policies(tmp_path):
    f = tmp_path / "support.yaml"
    f.write_text("name: Sam\ntask: support\npolicies:\n  floor: {type: threshold, default: 0.7, fallback: carry_on}\n  quiet: argmax\n")
    p = Profile.load(f)
    assert isinstance(p.policies["floor"], ThresholdPolicy) and p.policies["floor"].default == 0.7
    assert isinstance(p.policies["quiet"], ArgmaxPolicy)


def loud(db: float) -> bytes:
    """A 200 ms PCM16 frame at roughly this loudness in dB (a square wave at that RMS)."""
    import numpy as np
    a = int(32767 * 10 ** (db / 20))
    return (np.array([a, -a] * 1600, dtype=np.int16)).tobytes()


async def test_not_said_to_me_is_offered_only_after_the_first_answer_and_drops_the_words():
    answers = {**TURN, "kind": {"reply": 0.2, "sound": 0.1, "elsewhere": 0.7}}
    s, events, judge = make(answers, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    s.cfg.not_for_me = True
    await s.on_segment(Segment("Turn off the lights."))         # the call's first words: always the caller's
    await asyncio.sleep(0.05)
    assert s.utt is not None and not any(e.get("what") == "not_for_me" for e in events)
    s.user_turns = 1                                           # after one answer the choice is offered
    s.utt = None
    await s.on_segment(Segment("Honey, did you feed the cat?"))
    await asyncio.sleep(0.05)
    assert any(e.get("what") == "not_for_me" and e["why"] == "jev" for e in events)
    assert s.utt is None and not s.ledger.turns


async def test_a_voice_far_under_the_caller_is_not_answered():
    s, events, _ = make(TURN, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    s.cfg.far_db = 10
    s.caller_levels = [-14.0]                                  # the caller's answered words
    s.vad.voice = True
    for _ in range(5):
        await s.on_audio(loud(-30))                           # 16 dB under the caller: the room, not the caller
    s.vad.voice = False
    await s.on_segment(Segment("We should water the plants later."))
    await asyncio.sleep(0.05)
    assert any(e.get("what") == "not_for_me" and e["why"] == "far" for e in events)
    assert not any(e["type"] == "line" for e in events)


async def test_a_long_listening_sound_is_dropped():
    s, events, _ = make(TURN)
    s.cfg.listen_max_words = 3
    s.llm.out = ["Oh yeah? What do you have in mind?"]
    s.utt = None
    await s.listen_in("feeling")
    assert not any(e["type"] == "listen" for e in events)


def test_presets_carry_production_and_tested_settings():
    from jev_interaction.presets import config
    prod = config("production")
    assert prod.quiet_marks_s[-1] == 240.0 and prod.hold_after_ms == 400 and not prod.not_for_me
    tested = config("tested", language="zh")
    assert tested.hold_after_ms == 1000 and tested.not_for_me and tested.far_db == 10.0 and tested.language == "zh"
    with pytest.raises(KeyError):
        config("nope")


def test_every_example_profile_loads_with_a_card():
    import pathlib
    for f in sorted((pathlib.Path(__file__).resolve().parents[1] / "examples" / "profiles").glob("*.yaml")):
        p = Profile.load(f)
        d = p.extra.get("display") or {}
        assert p.name and p.manner and d.get("title") and d.get("title_zh") and d.get("language") in ("en", "zh"), f.name


def test_dashscope_messages_and_closed_sentences():
    from jev_interaction.adapters.dashscope_asr import closed_sentence, finish_task, run_task
    from jev_interaction.adapters.dashscope_tts import tts_continue, tts_run_task
    rt = run_task("t1", "paraformer-realtime-v2", 16000, ["zh", "en"], 400)
    assert rt["header"]["action"] == "run-task" and rt["payload"]["parameters"]["sample_rate"] == 16000
    assert finish_task("t1")["header"]["task_id"] == "t1"
    partial = {"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"text": "你好", "end_time": None}}}}
    done = {"header": {"event": "result-generated"}, "payload": {"output": {"sentence": {"text": "你好呀。", "sentence_end": True}}}}
    assert closed_sentence(partial) is None and closed_sentence(done) == "你好呀。"
    assert tts_run_task("t2", "cosyvoice-v2", "longcheng_v2", 24000)["payload"]["parameters"]["voice"] == "longcheng_v2"
    assert tts_continue("t2", "嗨")["payload"]["input"]["text"] == "嗨"


def test_reasoning_is_switched_off_where_the_provider_has_a_switch():
    from jev_interaction.adapters.openai_compat import no_reasoning
    assert no_reasoning("https://api.x.ai/v1") == {"reasoning_effort": "none"}
    assert no_reasoning("https://ark.ap-southeast.bytepluses.com/api/v3") == {"thinking": {"type": "disabled"}}
    assert no_reasoning("https://dashscope.aliyuncs.com/compatible-mode/v1") == {"enable_thinking": False}
    assert no_reasoning("https://api.openai.com/v1") == {} and no_reasoning("http://localhost:11434/v1") == {}
