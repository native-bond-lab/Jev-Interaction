import asyncio
import json
import pathlib
import time

import pytest

from jev_interaction import ArgmaxPolicy, Profile, SamplePolicy, ThresholdPolicy
from jev_interaction.adapters.base import Segment
from jev_interaction.judge import questions as Q


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
    assert set(Q.listen("Mara")["criteria"]) == {"due", "fits", "quiet", "answer_due"}


from jev_interaction.testing import FakeASR, FakeJudge, FakeLLM, FakeVAD, scripted_session  # noqa: E402,F401


def make(answers, policies=None):
    return scripted_session(answers, policies)


TURN = {"done": {"finished": 0.9, "continuing": 0.1},
        "pace_patient": {"yes": 0.4, "no": 0.6},               # the pace: one yes/no fact per pace; the rest unanswered
        "listen": {"due": 0, "fits": 0, "quiet": 1.0, "answer_due": 0}}


async def test_a_finished_turn_is_answered_and_the_pace_timing_is_blended():
    s, events, judge = make(TURN, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    await s.on_segment(Segment("How was your day?"))
    await asyncio.sleep(0.05)
    assert "Chatty listener." in judge.asked[0][1]["call"]              # the persona's manner is in every state
    s.silence_ms = 400
    await s.tick()
    assert any(e["type"] == "line" and e["text"] == "Hey." for e in events)
    assert s.ledger.turns[0].text == "How was your day?" and "event: they spoke" in s.ledger.turns[0].data_line
    assert s.params().max_wait_ms == int(0.6 * 1200 + 0.4 * 2500)


async def test_talking_over_the_agent_never_pauses_the_line_and_the_floor_question_decides():
    s, events, _ = make({"floor": {"carry_on": 0.1, "yield": 0.8, "finish_first": 0.1, "jump_in": 0.0}})
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    s.vad.voice = True
    for _ in range(3):
        await s.on_audio(b"\x00" * 6400)
    assert not any(e["type"] in ("hold", "stop") for e in events)        # a voice over the line: no clock touches it
    await s.on_segment(Segment("Wait, can I ask something?"))
    await asyncio.sleep(0.05)
    assert any(e["type"] == "stop" for e in events)
    assert s.ledger.last_agent().cut


async def test_words_not_yet_closed_are_put_to_jev_once_the_voice_has_been_over_the_line_a_while():
    s, events, judge = make({"floor": {"carry_on": 0.9, "yield": 0.1, "finish_first": 0.0, "jump_in": 0.0}})
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    s.vad.voice = True
    await s.on_audio(b"\x00" * 6400)
    await s.on_segment(Segment("wait", final=False))                     # 200 ms over the line: too soon to ask
    await asyncio.sleep(0.05)
    assert not judge.asked
    await s.on_audio(b"\x00" * 6400)                                    # 400 ms, and there are words: Jev is asked
    await asyncio.sleep(0.05)
    assert len(judge.asked) == 1 and 'the user is saying: "wait"' in judge.asked[0][1]
    assert not any(e["type"] in ("stop", "decision") for e in events) and s.utt is not None   # "carry on": nothing happens
    await s.on_segment(Segment("wait can I", final=False))               # more words, but not yet as much voice again
    await asyncio.sleep(0.05)
    assert len(judge.asked) == 1
    judge.answers = {"floor": {"carry_on": 0.1, "yield": 0.8, "finish_first": 0.1, "jump_in": 0.0}}
    for _ in range(2):
        await s.on_audio(b"\x00" * 6400)
    await asyncio.sleep(0.05)
    assert len(judge.asked) == 2 and any(e["type"] == "stop" for e in events)   # the user needs the floor: the line stops
    assert s.utt is not None and not s.utt.segments                      # before the recognizer has closed a word
    stop = [e for e in events if e["type"] == "decision"][-1]
    assert stop["action"] == "yield" and stop["early"]


async def test_a_sound_over_the_line_with_no_words_asks_nothing():
    s, events, judge = make({"floor": {"carry_on": 0.1, "yield": 0.9}})
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    s.vad.voice = True
    for _ in range(5):
        await s.on_audio(b"\x00" * 6400)                                # a laugh, a second long
    assert not judge.asked and not events


QUIET_FACTS = {"turn": {"theirs": 0.1, "ours": 0.9}, "busy": {"busy": 0.0, "not_busy": 1.0},
               "bye": {"goodbye": 0.0, "going": 1.0}, "gone": {"unanswered": 0.0, "not_yet": 1.0}}


def quiet_facts(**changed) -> dict:
    """A fake judge's answers to the quiet facts, asked in both option orders (decisions/quiet.py)."""
    facts = {**QUIET_FACTS, **changed}
    return {**facts, **{k + "__r": v for k, v in facts.items()}}


async def test_a_quiet_line_may_be_picked_up_and_hang_up_is_never_first():
    s, events, _ = make(quiet_facts(bye={"goodbye": 0.95, "going": 0.05}))
    s.ledger.agent("Bye then.")
    await s.ask_quiet(30.0)                                              # the call has ended, but nothing was said into
    done = [e for e in events if e.get("what") == "quiet"]               # the quiet yet: she checks first
    assert done[-1]["action"] == "check" and not s.hanging_up and s.spoke_into_quiet == 1
    s.speaking = False
    await s.ask_quiet(30.0)
    assert [e for e in events if e.get("what") == "quiet"][-1]["action"] == "hang_up" and s.hanging_up


async def test_what_is_done_in_a_quiet_follows_whose_move_it_is_and_how_long_it_has_been():
    async def after(quiet_s, pace="normal", **facts):
        s, events, _ = make(quiet_facts(**facts))
        s.pace = pace
        s.ledger.agent("So that was my week.")
        await s.ask_quiet(quiet_s)
        return next(e["action"] for e in events if e.get("what") == "quiet")
    theirs = {"turn": {"theirs": 0.9, "ours": 0.1}}
    assert await after(4.0) == "wait" and await after(8.0) == "go_on"            # her own move: after the pace's lead_after_s
    assert await after(4.0, "narrate") == "go_on" and await after(8.0, "patient") == "wait"
    assert await after(8.0, **theirs) == "wait" and await after(12.0, **theirs) == "check"    # theirs: let it be, then check
    assert await after(12.0, busy={"busy": 0.9, "not_busy": 0.1}) == "check"     # "one moment": theirs as well
    s, events, _ = make({})                                                      # a judge that answers nothing: nothing said
    await s.ask_quiet(30.0)
    assert not any(e["type"] == "line" for e in events)


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


async def test_a_pause_asks_only_what_is_read_and_the_draw_does_not_wait():
    s, events, judge = make(TURN, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    await s.on_segment(Segment("So what do you think?"))
    await asyncio.sleep(0.05)
    asked = judge.asked[0][0]
    assert "done" in asked and "pace_patient" in asked and "wait" not in asked and "kind" not in asked   # nothing reads those
    assert "pace" not in asked and "pace_normal" not in asked  # the pace a call starts in is none of the others being so
    s.silence_ms = 200                                         # one frame of quiet: the answer is drawn on at once
    await s.tick()
    assert any(e.get("what") == "end_of_turn" and e["go"] for e in events)


async def test_the_last_words_wording_asks_about_the_users_words_both_ways_round_and_averages():
    answers = {**TURN, "done": {"finished": 0.9, "continuing": 0.1}, "done_again": {"finished": 0.5, "continuing": 0.5}}
    s, events, judge = make(answers, {"end_of_turn": SamplePolicy(rng=lambda: 0.1)})
    s.cfg.turn_question = "last_words"
    await s.on_segment(Segment("So what do you think?"))
    await asyncio.sleep(0.05)
    asked, state = judge.asked[0]
    assert {"done", "done_again", "pace_patient"} <= asked             # the other questions ride along and read the text under `call`
    from jev_interaction.judge import questions as Q
    both = Q.last_words()
    assert list(both["done"]["criteria"]) == ["finished", "continuing"] and list(both["done_again"]["criteria"]) == ["continuing", "finished"]
    assert state["user_latest_words"] == "So what do you think?" and "Phone call between the user and" in state["call"]
    assert abs(s.judged["finished"] - 0.7) < 1e-9              # the two orders, averaged


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
    s._open_utterance()
    s.utt.segments.append((0.0, "so I was thinking,"))
    await s.listen_in()
    assert not any(e["type"] == "listen" for e in events) and not s.utt.asides      # not voiced, not in the record


def test_presets_carry_recommended_and_tested_settings():
    from jev_interaction.presets import config
    prod = config("recommended")
    assert config("production") == prod                                  # its earlier name
    assert prod.quiet_marks_s[-1] == 240.0 and prod.overlap_ask_ms == 400 and not prod.not_for_me
    tested = config("tested", language="zh")
    assert tested.overlap_ask_ms == 1000 and tested.not_for_me and tested.far_db == 10.0 and tested.language == "zh"
    with pytest.raises(KeyError):
        config("nope")


def test_every_example_profile_loads_with_a_card():
    import pathlib
    for f in sorted((pathlib.Path(__file__).resolve().parents[1] / "jev_interaction" / "profiles").glob("*.yaml")):
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


async def test_a_failing_judge_leaves_the_line_playing():
    class BrokenJudge:
        async def ask(self, questions, state):
            raise RuntimeError("judge down")
    s, events, _ = make({})
    s.judge = BrokenJudge()
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    s.vad.voice = True
    for _ in range(3):
        await s.on_audio(b"\x00" * 6400)
    await s.on_segment(Segment("Wait, what?"))
    await asyncio.sleep(0.05)
    assert not any(e["type"] == "stop" for e in events)
    assert any(e["type"] == "error" and e["what"] == "judge" for e in events)


def test_settings_are_written_only_from_this_servers_own_page(monkeypatch):
    from jev_interaction.server import settings as S
    monkeypatch.delenv("SETTINGS_WRITABLE", raising=False)
    assert S.is_writable("127.0.0.1", "localhost:8080", "http://localhost:8080")
    assert S.is_writable("::1", "[::1]:8080", "")
    assert not S.is_writable("192.168.1.9", "localhost:8080", "")                    # another machine
    assert not S.is_writable("127.0.0.1", "localhost:8080", "https://evil.example")    # another site in this browser
    assert not S.is_writable("127.0.0.1", "evil.example:8080", "http://evil.example")  # DNS rebinding


def test_settings_write_keeps_other_lines_and_rejects_unknown_names(tmp_path, monkeypatch):
    from jev_interaction.server import settings as S
    env = tmp_path / ".env"
    env.write_text("# keys\nJEV_API_KEY=old\nOTHER=1\n")
    monkeypatch.setattr(S, "ENV_FILE", env)
    S.write({"JEV_API_KEY": "new", "LLM_MODEL": "grok-4.3"})
    text = env.read_text()
    assert "# keys" in text and "JEV_API_KEY=new" in text and "OTHER=1" in text and "LLM_MODEL=grok-4.3" in text
    with pytest.raises(KeyError):
        S.write({"PATH": "/tmp"})


def test_the_voice_key_is_tts_api_key_and_the_old_names_still_work(monkeypatch):
    from jev_interaction.adapters import registry as R
    from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
    for k in ("TTS_API_KEY", "TTS_VOICE_ID"):
        monkeypatch.setenv(k, "x")                                     # so that teardown removes what legacy_env sets
        monkeypatch.delenv(k)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_old")                  # a deployment's secrets from 0.2.x
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v_old")
    tts = ElevenLabsTTS()
    assert (tts.key, tts.voice) == ("sk_old", "v_old")
    R.legacy_env()
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    assert "TTS_API_KEY" not in R.missing_settings() and "TTS_VOICE_ID" not in R.missing_settings()
    monkeypatch.setenv("TTS_API_KEY", "sk_new")                         # the new name wins
    assert ElevenLabsTTS().key == "sk_new"
    names = {s.name for p in R._PROVIDERS.values() for s in p.settings}
    assert "TTS_API_KEY" in names and not any(n.startswith("ELEVENLABS_API") or n == "ELEVENLABS_VOICE_ID" for n in names)


def test_provider_registry_drives_factories_health_and_settings(monkeypatch):
    from jev_interaction.adapters import registry as R
    for k in ("JEV_API_KEY", "LLM_API_KEY", "LLM_BASE_URL", "TTS_API_KEY", "TTS_VOICE_ID", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k in ("ASR_PROVIDER", "TTS_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert R.missing_settings() == ["JEV_API_KEY", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "ASR_PROVIDER", "TTS_PROVIDER"]
    monkeypatch.setenv("ASR_PROVIDER", "dashscope")                    # speech is never chosen for the user
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("LLM_MODEL", "llama3")
    assert R.missing_settings() == ["JEV_API_KEY", "LLM_BASE_URL", "LLM_API_KEY", "DASHSCOPE_API_KEY", "TTS_API_KEY",
                                    "TTS_VOICE_ID"]
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")      # a local model needs no key
    assert "LLM_API_KEY" not in R.missing_settings()
    R.register("asr", "toy", lambda language="en", **_: ("toy-asr", language), [R.Setting("TOY_KEY", "Toy key", secret=True, required=True)])
    monkeypatch.setenv("ASR_PROVIDER", "toy")
    assert R.create("asr", language="zh") == ("toy-asr", "zh") and "TOY_KEY" in R.missing_settings()
    from jev_interaction.server import settings as S
    asr = next(s for s in S.steps() if s["id"] == "asr")
    toy = next(p for p in asr["providers"] if p["name"] == "toy")
    assert asr["selected"] == "toy" and toy["missing"] == ["TOY_KEY"] and not asr["ready"]
    R._PROVIDERS.pop(("asr", "toy"))


def test_no_speech_provider_is_chosen_for_the_user(monkeypatch):
    from jev_interaction.adapters import registry as R
    monkeypatch.delenv("TTS_PROVIDER", raising=False)
    assert R.selected("tts") is None and R.speech_style() == "plain"
    with pytest.raises(R.NotChosen):
        R.create("tts")


def test_the_language_model_is_told_how_to_write_for_the_voice(monkeypatch):
    from jev_interaction.adapters import registry as R
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")
    assert R.speech_style() == "audio_tags" and "[laughs]" in R.speech_prompt()
    s, _, _ = make({})
    assert "[laughs]" in s.system                                          # the session picks it up from the registry
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")   # an older model reads tags aloud
    assert R.speech_style() == "plain"
    monkeypatch.setenv("TTS_PROVIDER", "dashscope")
    assert R.speech_style() == "plain" and "no stage directions" in R.speech_prompt()
    R.register_style("whisper_only", "Whisper everything.")
    R.register("tts", "toy", lambda **_: None, speech=lambda: "whisper_only")
    assert R.speech_prompt("toy") == "Whisper everything."
    R._PROVIDERS.pop(("tts", "toy"))


def test_a_pasted_key_is_recognised_by_its_shape():
    from jev_interaction.adapters import registry as R
    ids = lambda kind, key: [c["id"] for c in R.detect(kind, key)]  # noqa: E731
    assert ids("llm", "xai-" + "a" * 40) == ["xai"]
    assert ids("llm", "sk-proj-" + "a" * 40) == ["openai"]
    assert ids("llm", "sk-or-v1-" + "a" * 40) == ["openrouter"]
    assert ids("llm", "gsk_" + "a" * 40) == ["groq"]
    plain = ids("llm", "sk-" + "0123456789abcdef" * 2)                  # several vendors share this shape: all offered
    assert {"openai", "deepseek", "dashscope", "moonshot"} <= set(plain)
    assert ids("llm", "01234567-89ab-cdef-0123-456789abcdef")[:2] == ["volcengine", "byteplus"]
    assert ids("tts", "sk_" + "0123456789abcdef" * 3) == ["elevenlabs"]
    assert ids("asr", "sk-" + "0123456789abcdef" * 2) == ["dashscope"]
    assert R.detect("llm", "") == []


def test_reference_setups_match_env_example_and_are_not_the_default():
    from jev_interaction.server import settings as S
    text = (pathlib.Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    active = S.parse_env(pathlib.Path(__file__).resolve().parents[1] / ".env.example")
    for name, values in S.TEMPLATES.items():
        for k, v in values.items():
            assert active.get(k) == v or f"# {k}={v}" in text, (name, k, v)
    for k in ("LLM_BASE_URL", "LLM_MODEL", "ASR_PROVIDER", "TTS_PROVIDER"):
        assert active[k] == ""                                             # vendors are the user's choice


def test_profiles_by_id_and_user_override(tmp_path, monkeypatch):
    from jev_interaction.server import paths
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    found = paths.profiles()
    assert {"companion", "support", "vera", "puppy_zh"} <= set(found)
    (tmp_path / "profiles").mkdir()
    mine = tmp_path / "profiles" / "support.yaml"
    mine.write_text("name: Mine\n", encoding="utf-8")
    assert paths.profiles()["support"] == mine
    assert paths.env_file() == tmp_path / ".env"
    assert Profile.load("support").name and Profile.load(mine).name == "Mine"


def test_voice_overrides(monkeypatch):
    from jev_interaction.server import app as server
    monkeypatch.setenv("TTS_VOICES", "companion=abc, vera = xyz ,bad,=nope")
    assert server.voice_overrides() == {"companion": "abc", "vera": "xyz"}


def test_key_fields_are_not_password_fields():
    """Browser password managers save the first key typed into a password field and fill it into every other one."""
    web = pathlib.Path(__file__).resolve().parents[1] / "jev_interaction" / "server" / "web"
    for f in web.glob("*.*"):
        text = f.read_text(encoding="utf-8")
        assert "type: 'password'" not in text and 'type="password"' not in text and "? 'text' : 'password'" not in text, f.name


async def test_the_agents_own_words_back_through_the_microphone_are_not_the_users():
    s, events, _ = make({"floor": {"carry_on": 0.0, "yield": 1.0, "finish_first": 0.0, "jump_in": 0.0}})
    s.speaking = True
    s.ledger.agent("So the thing about my morning is the swell came in early.")
    s.lines["a"] = "So the thing about my morning is the swell came in early."
    await s.on_segment(Segment("the thing about my morning"))            # a speaker next to the microphone
    await asyncio.sleep(0.05)
    assert s.utt is None and not any(e["type"] in ("stop", "user") for e in events)
    await s.on_segment(Segment("Wait, can I ask something?"))            # the user's own words still take the floor
    await asyncio.sleep(0.05)
    assert any(e["type"] == "stop" for e in events)


async def test_a_detector_that_measures_voice_is_asked_how_much_and_told_when_the_line_plays():
    s, events, _ = make({})

    class Measured:
        asked = []

        def voiced_ms(self, pcm, playing=False):
            self.asked.append(playing)
            return 80                                                    # 80 ms of voice in every 200 ms frame

    s.vad = Measured()
    s.speaking = True
    for _ in range(4):
        await s.on_audio(b"\x00" * 6400)
    assert s.vad.asked == [True] * 4
    assert s.utt.speech_ms == 320 and s.utt.over_ms == 320               # the voice in the frames, not the frames


def test_the_energy_detector_raises_its_bar_while_the_line_plays():
    import numpy as np

    from jev_interaction.adapters import EnergyVAD
    tone = (np.sin(np.arange(3200) * 0.2) * 0.03 * 32767).astype(np.int16).tobytes()   # a faint sound: an echo off a speaker
    assert EnergyVAD().voiced_ms(tone) == 200 and EnergyVAD().voiced_ms(tone, playing=True) == 0


async def test_a_sound_before_the_line_does_not_count_as_voice_over_it():
    s, events, _ = make({})
    s.vad.voice = True
    for _ in range(3):
        await s.on_audio(b"\x00" * 6400)                                # a cough while nobody is speaking
    s.speaking = True                                                    # the agent's line starts
    await s.on_audio(b"\x00" * 6400)
    assert s.utt.over_ms == 200                                          # 200 ms over the line, not 800


async def test_a_wordless_sound_is_over_after_a_quiet_stretch():
    s, _, _ = make({})
    s.vad.voice = True
    await s.on_audio(b"\x00" * 6400)
    s.vad.voice = False
    for _ in range(8):
        await s.on_audio(b"\x00" * 6400)
    assert s.utt is None


async def test_words_over_a_line_that_goes_on_are_in_the_record_at_once():
    s, events, _ = make({"floor": {"carry_on": 0.9, "yield": 0.1, "finish_first": 0.0, "jump_in": 0.0}})
    s.speaking = True
    s.ledger.agent("So there I was, forty seconds of dead air")
    s.vad.voice = True
    for _ in range(2):
        await s.on_audio(b"\x00" * 6400)
    await s.on_segment(Segment("no way"))
    await asyncio.sleep(0.05)
    assert not any(e["type"] in ("hold", "unhold", "stop") for e in events)
    assert s.utt is None and s.ledger.turns[-1].over                     # in the record at once; the story goes on
    assert s.ledger.messages()[-1] == {"role": "user", "content": "(over you: no way)"}
    assert "who went on): no way" in s.ledger.recent_text("Mara", 8, 300)
    s.ledger.user("so what happened", "[event]")
    assert s.ledger.messages()[-1]["content"] == "(over you: no way)\n[event]\nso what happened"
    s.ledger.turns.pop()
    await s.on_audio(b"\x00" * 6400)                                    # a laugh a little later: a new sound, from nothing
    assert s.utt is not None and s.utt.over_ms == 200


async def test_a_caller_waits_in_line_until_a_call_ends_and_is_told_where_they_stand(monkeypatch):
    from jev_interaction.server import app as server

    class Sock:
        def __init__(self):
            self.sent, self.inbox = [], asyncio.Queue()

        async def send_text(self, text):
            self.sent.append(json.loads(text))

        async def receive(self):
            return await self.inbox.get()

    monkeypatch.setattr(server, "MAX_CALLS", 1)
    monkeypatch.setattr(server, "MAX_CALL_S", 300.0)
    monkeypatch.setattr(server, "ACTIVE", {"calls": 1})
    monkeypatch.setattr(server, "STARTS", [time.monotonic() - 240])          # the call in progress has a minute left
    first, second, gone = object(), object(), object()
    monkeypatch.setattr(server, "WAITING", [first, second, gone])
    a, b, c = Sock(), Sock(), Sock()
    waits = [asyncio.create_task(server.wait_in_line(s, tk)) for s, tk in ((a, first), (b, second), (c, gone))]
    await asyncio.sleep(0.05)
    assert a.sent == [{"type": "queue", "ahead": 0, "wait_s": a.sent[0]["wait_s"]}] and 55 <= a.sent[0]["wait_s"] <= 60
    assert b.sent == [{"type": "queue", "ahead": 1, "wait_s": None}]         # further back than the calls in progress: no promise
    await c.inbox.put({"type": "websocket.disconnect"})                      # the third hangs up while waiting
    assert await waits[2] is False
    await a.inbox.put({"type": "websocket.receive", "bytes": b"\0" * 6400})  # audio sent while in line is ignored
    await asyncio.sleep(0.05)
    assert not waits[0].done()
    server.ACTIVE["calls"] = 0                                               # the call ends: the first in line gets it
    assert await asyncio.wait_for(waits[0], 3) is True and a.sent[-1] == {"type": "ready"}
    server.WAITING.remove(first)
    server.WAITING.remove(gone)
    server.ACTIVE["calls"] = 1
    await asyncio.sleep(1.2)
    assert not waits[1].done() and b.sent[-1]["ahead"] == 0                  # the second moved up and was told
    waits[1].cancel()


def test_a_line_of_tags_alone_has_no_voice():
    from jev_interaction import speaking
    assert not speaking.has_voice("[laughs]") and not speaking.has_voice("[quiet breath] …") and not speaking.has_voice("")
    assert speaking.has_voice("[laughs] ha") and speaking.has_voice("Mm.") and speaking.has_voice("[soft] 嗯")


@pytest.mark.asyncio
async def test_a_listening_sound_is_measured_in_characters_where_words_have_no_spaces():
    s, events, _ = scripted_session()
    s._open_utterance()
    s.utt.segments.append((0.0, "我小时候住在海边，"))
    s.llm.out = ["那时候大概十一二岁吧，我也记不清了。"]      # one "word" to str.split, a whole sentence to the ear
    await s.listen_in()
    assert not any(e["type"] == "listen" for e in events)
    s.llm.out = ["嗯？"]
    s.listen_last = 0
    await s.listen_in()
    await s.listen_in()                                # right behind the first: not voiced, they would run together
    assert [e["text"] for e in events if e["type"] == "listen"] == ["嗯？"]


@pytest.mark.asyncio
async def test_heard_keeps_the_lines_that_played_and_names_its_reply():
    s, _, _ = scripted_session()
    s.llm.out = ["I was eight.", "My dad took me to the pier.", "A wave took my shorts."]
    await s.respond("commit")
    story, gen = s.ledger.last_agent(), s.gen
    await s._stop_line()
    s.llm.out = ["Eight."]
    await s.respond("commit")                         # the next reply is already in the record when `heard` arrives
    await s.on_client({"type": "heard", "gen": gen, "text": "I was eight.\nMy dad took"})
    assert (story.text, story.cut) == ("I was eight.\nMy dad took", True)
    assert s.ledger.last_agent().text == "Eight." and not s.ledger.last_agent().cut
    await s.on_client({"type": "heard", "gen": s.gen, "text": ""})      # none of it was played
    assert (s.ledger.last_agent().text, s.ledger.last_agent().cut) == ("", True)


@pytest.mark.asyncio
async def test_sure_the_line_should_stop_but_split_on_how_it_stops():
    async def floor(probs):
        s, events, _ = scripted_session({"floor": probs})
        s.pace = "eager"                                # offers overrule; the line stops at p(yield) >= 0.6
        s.speaking = True
        s.ledger.agent("And another thing about that wave")
        await s.on_segment(Segment("Let me finish!"))
        await asyncio.sleep(0.05)
        return [e["action"] for e in events if e["type"] == "decision" and e["what"] == "floor"]
    assert await floor({"carry_on": 0.09, "yield": 0.43, "overrule": 0.48}) == ["overrule"]     # was: carried on
    assert await floor({"carry_on": 0.07, "yield": 0.49, "overrule": 0.44}) == ["yield"]
    assert await floor({"carry_on": 0.55, "yield": 0.25, "overrule": 0.20}) == ["carry_on"]     # going on is likelier
    assert await floor({"carry_on": 0.30, "finish_first": 0.25, "yield": 0.25, "overrule": 0.20}) == ["carry_on"]


@pytest.mark.asyncio
async def test_a_reply_that_fails_or_says_nothing_is_asked_for_once_more():
    class Flaky:
        def __init__(self, outs):
            self.outs, self.calls = list(outs), 0

        async def lines(self, messages, max_tokens=160):
            self.calls += 1
            out = self.outs.pop(0)
            if isinstance(out, Exception):
                raise out
            for x in out:
                yield x

    s, events, _ = scripted_session()
    s.llm = Flaky([RuntimeError("503"), ["Still here."]])
    await s.respond("commit")
    assert s.llm.calls == 2 and [e["text"] for e in events if e["type"] == "line"] == ["Still here."]
    s.llm = Flaky([["[sighs]"], []])                       # nothing a voice can say, then nothing at all
    await s.respond("commit")
    assert s.llm.calls == 2 and not s.generating and not s.speaking
    assert [e["what"] for e in events if e["type"] == "error"] == ["responder"]
    s.llm = Flaky([["Hi."]])
    await s.respond("commit")
    assert s.llm.calls == 1                                 # a reply that came is not asked for again


@pytest.mark.asyncio
async def test_jev_picks_the_moment_and_the_responder_the_words_of_what_is_put_in():
    import time

    from jev_interaction.decisions.listen import LISTEN
    from jev_interaction.utterance import Utterance
    s, events, _ = scripted_session(policies={"listen": ThresholdPolicy(default=0.5)}, listen_gap_jitter=0)
    said = lambda: [(e["kind"], e["text"]) for e in events if e["type"] == "listen"]  # noqa: E731
    due = {"listen": {"probabilities": {"due": 0.9, "quiet": 0.1}}}
    fits = {"listen": {"probabilities": {"fits": 0.9, "quiet": 0.1}}}
    s.utt = Utterance(1, time.monotonic(), [(0.0, "two cartons of milk,")])
    s.llm.out = ["Two cartons of milk."]
    await LISTEN.apply(s, due, {})
    await asyncio.sleep(0.05)
    assert said() == [("due", "Two cartons of milk.")]
    asked = s.llm.seen[-1][-1]["content"]                  # the event says which moment it is; none of their words quoted
    assert asked.endswith("two cartons of milk,") and "waiting to hear from you" in asked and '"two cartons' not in asked
    assert f'and {s.p.short} put in: "Two cartons of milk."' in LISTEN.state(s, {})    # Jev reads what was put in
    assert s.ledger.open is s.utt                          # one record: the turn in progress is part of the call

    s.listen_last = time.monotonic() - 1.5                 # asked again about the same words as the quiet grows: it came
    await LISTEN.apply(s, due, {})                         # up once, however sure Jev is the second time
    await asyncio.sleep(0.05)
    assert len(said()) == 1

    s.utt.segments.append((0.0, "a dozen eggs,"))          # the next piece, well inside the gap optional sounds keep
    s.listen_last = time.monotonic() - 1.5
    s.llm.out = ["A dozen eggs."]
    assert LISTEN.ready(s, {})
    await LISTEN.apply(s, due, {})
    await asyncio.sleep(0.05)
    assert said()[-1] == ("due", "A dozen eggs.")
    assert s.llm.seen[-1][-1]["content"].endswith("a dozen eggs,")   # the words since, not the list so far

    s.utt.segments.append((0.0, "and, um,"))
    s.listen_last = time.monotonic() - 1.5
    s.llm.out = ["Mm."]
    await LISTEN.apply(s, fits, {})                        # a sound that could be left out still waits its three seconds
    await asyncio.sleep(0.05)
    assert len(said()) == 2
    s.listen_last = time.monotonic() - 3.5
    await LISTEN.apply(s, fits, {})
    await asyncio.sleep(0.05)
    assert said()[-1] == ("fits", "Mm.")                   # and a bare "mm" is in the record like anything else put in
    s.utt.segments.append((0.0, "that's all."))
    s.listen_last = time.monotonic() - 3.5
    s.llm.out = [""]
    await LISTEN.apply(s, fits, {})                        # the responder may write nothing: then nothing is put in
    await asyncio.sleep(0.05)
    assert len(said()) == 3
    s.llm.out = ["Got it."]
    await s.respond("spoke")                               # the turn's record has what was put in, where it came
    name = s.p.short
    assert s.ledger.turns[-2].text == (f"two cartons of milk, [{name}: Two cartons of milk.] a dozen eggs, "
                                       f"[{name}: A dozen eggs.] and, um, [{name}: Mm.] that's all.")
    said_by = [(m["role"], m["content"].split("\n")[-1]) for m in s.llm.seen[-1][-7:]]   # the agent's words are its own turns
    assert said_by == [("user", "two cartons of milk,"), ("assistant", "Two cartons of milk."), ("user", "a dozen eggs,"),
                       ("assistant", "A dozen eggs."), ("user", "and, um,"), ("assistant", "Mm."), ("user", "that's all.")]


@pytest.mark.asyncio
async def test_a_silence_after_unfinished_words_stays_the_users_until_jev_is_sure_or_it_has_gone_on_long():
    import time

    from jev_interaction.decisions.turn import TURN as TURN_DECISION
    from jev_interaction.utterance import Utterance
    s, _, judge = scripted_session({"done": {"finished": 0.2, "continuing": 0.8}},
                                   policies={"end_of_turn": ThresholdPolicy(default=0.5)})
    s.utt = Utterance(1, time.monotonic(), [(0.0, "and it pushed my cup off too.")])
    s.judged = {"finished": 0.2, "drawn": True}
    asked = len(s.llm.seen)
    s.silence_ms = s.cfg.pace("normal").max_wait_ms + 1000         # past the longest wait: no clock hands her the turn
    assert not await TURN_DECISION.on_tick(s, time.monotonic())
    assert len(s.llm.seen) == asked and s.utt is not None
    s.silence_ms = s.cfg.turn_reask_ms[-1]                         # the quiet grows: Jev is asked again, the listen
    await TURN_DECISION.on_tick(s, time.monotonic())               # question with it
    await asyncio.sleep(0.05)
    assert "listen" in judge.asked[-1][0] and "quiet for 4.0 s" in judge.asked[-1][1]["call"]
    s.silence_ms = s.cfg.pace("normal").max_wait_ms + s.cfg.turn_last_ms
    assert await TURN_DECISION.on_tick(s, time.monotonic())        # a long silence: she speaks, and her line is told why
    assert "silent for" in s.llm.seen[-1][-1]["content"] and s.utt is None


@pytest.mark.asyncio
async def test_someone_else_is_put_on_the_line_when_the_user_asks_for_them():
    lyra = Profile(name="Lyra Vex", task="a companion", prompt="You are Lyra.", manner="Chatty listener.")
    vera = Profile(name="Vera", task="a speaking coach", prompt="You are Vera.", manner="Few words.",
                   policies={"quiet": ArgmaxPolicy()}, extra={"display": {"accent": "#e5e7eb"}})
    answers = {**TURN, "who": {"stay": 0.1, "vera": 0.9}}
    s, events, judge = scripted_session(answers, profile=lyra, policies={"end_of_turn": ThresholdPolicy(default=0.5)})
    s.cast = {"lyra": lyra, "vera": vera}
    await s.respond("pickup")
    s.speaking = False                                               # her greeting has played
    s.llm.out = ["Sure, one second."]
    s._open_utterance()
    s.utt.segments.append((0.0, "Can you put Vera on? I have a talk tomorrow."))
    from jev_interaction.decisions.turn import TURN as TURN_DECISION
    await TURN_DECISION.ask(s, utt_id=s.utt.id)
    assert "who" in judge.asked[-1][0] and s.judged["who"] == "vera"
    s.silence_ms = 200
    assert await TURN_DECISION.on_tick(s, 0.0)                       # the turn is taken: a word from Lyra, then Vera is on
    assert s.p is vera and "You are Vera." in s.system and isinstance(s.policies["quiet"], ArgmaxPolicy)
    kinds = [(e["type"], e.get("id") or e.get("name")) for e in events if e["type"] in ("line", "persona")]
    assert [k for k, _ in kinds][-3:] == ["line", "persona", "line"]   # her goodbye in her voice, then the other's first line
    persona = next(e for e in events if e["type"] == "persona")
    assert persona["id"] == "vera" and persona["gen"] == s.gen and persona["accent"] == "#e5e7eb"
    leaving, arriving = s.llm.seen[-2], s.llm.seen[-1]
    assert "You are Lyra." in leaving[0]["content"] and "putting Vera on" in leaving[-1]["content"]
    assert "You are Vera." in arriving[0]["content"] and "was talking with Lyra and asked for you" in arriving[-1]["content"]
    assert not any(m["role"] == "assistant" for m in arriving)       # nothing Lyra said is Vera's own turn
    assert "(Lyra: Sure, one second.)" in arriving[-1]["content"] and "Can you put Vera on?" in arriving[-1]["content"]
    assert "Lyra: Sure, one second." in s.ledger.recent_text("Vera", 8, 300)   # and Jev reads who said what
    assert set(s.others()) == {"lyra"}                               # she can be asked back

    s2, _, judge2 = scripted_session({**TURN, "who": {"stay": 0.9, "vera": 0.1}}, profile=lyra)
    assert not s2.others()                                           # no cast: the question is not asked at all
    s2._open_utterance()
    s2.utt.segments.append((0.0, "Vera told me the same thing yesterday."))
    await TURN_DECISION.ask(s2, utt_id=s2.utt.id)
    assert "who" not in judge2.asked[-1][0] and s2.judged["who"] is None


def test_a_player_that_asks_for_byte_ranges_gets_them_and_the_others_get_the_stream():
    from fastapi.testclient import TestClient

    from jev_interaction.server import app as server
    from jev_interaction.testing import FakeSynthesizer

    class Counting(FakeSynthesizer):
        calls = 0

        async def audio(self, text):
            Counting.calls += 1
            yield text.encode("utf-8")[:4]
            yield text.encode("utf-8")[4:]

    server.LINES["abc"] = ("0123456789", Counting())
    c = TestClient(server.app)
    plain = c.get("/tts/abc")
    assert plain.status_code == 200 and plain.content == b"0123456789" and "content-range" not in plain.headers
    assert c.get("/tts/abc", headers={"Range": "bytes=0-"}).status_code == 200          # "all of it": still the stream
    probe = c.get("/tts/abc", headers={"Range": "bytes=0-1"})                           # Safari's first question
    assert probe.status_code == 206 and probe.content == b"01" and probe.headers["content-range"] == "bytes 0-1/10"
    assert probe.headers["accept-ranges"] == "bytes" and probe.headers["content-type"] == "audio/mpeg"
    rest = c.get("/tts/abc", headers={"Range": "bytes=2-"})
    assert rest.status_code == 206 and rest.content == b"23456789" and rest.headers["content-range"] == "bytes 2-9/10"
    assert c.get("/tts/abc", headers={"Range": "bytes=-3"}).content == b"789"
    assert c.get("/tts/abc", headers={"Range": "bytes=50-60"}).status_code == 416
    assert Counting.calls == 3                                                          # the ranges share one synthesis
    assert c.get("/tts/nope").status_code == 404


def test_health_is_the_whole_report():
    from fastapi.testclient import TestClient

    from jev_interaction.server import app as server
    h = TestClient(server.app).get("/api/health").json()
    assert isinstance(h, dict) and {"ready", "missing", "providers", "vad", "voiceprint"} <= set(h)


# ---------------------------------------------------------------- the Bailian question set (Config.judge_provider)
def both_ways(answers: dict) -> dict:
    """A fake judge's answers for questions asked in both option orders (judge/bailian.py): the same either way."""
    return {**answers, **{k + "__r": v for k, v in answers.items()}}


def test_bailian_merges_the_two_orders_and_turns_small_answers_into_the_engines_choices():
    from jev_interaction.judge import bailian as B
    asked = B.both("q", {"type": "choice", "instructions": "?", "criteria": {"a": "A", "b": "B"}})
    assert list(asked["q"]["criteria"]) == ["a", "b"] and list(asked["q__r"]["criteria"]) == ["b", "a"]
    merged = B.merge({"q": {"probabilities": {"a": 0.9, "b": 0.1}}, "q__r": {"probabilities": {"a": 0.5, "b": 0.5}}})
    assert set(merged) == {"q"} and abs(merged["q"]["probabilities"]["a"] - 0.7) < 1e-9 and merged["q"]["choice"] == "a"
    p = lambda **kw: {k: {"probabilities": v} for k, v in kw.items()}                       # noqa: E731
    quiet = B.quiet_probs(p(turn={"theirs": 1.0}, busy={"busy": 0.0}, bye={"goodbye": 0.0}, gone={"unanswered": 0.0},
                            long={"long": 1.0}))
    assert max(quiet, key=quiet.get) == "check"                 # their move, a long quiet: check on them
    quiet = B.quiet_probs(p(turn={"theirs": 0.0}, busy={"busy": 0.0}, bye={"goodbye": 0.0}, gone={"unanswered": 0.0},
                            long={"long": 0.0}))
    assert max(quiet, key=quiet.get) == "go_on"                 # the agent's move: pick the thread up
    listen = B.listen_probs(p(rule={"task": 0.9}, hit={"hit": 0.9}, ask={"asks": 0.0}, listen={"fits": 0.5, "quiet": 0.5}))
    assert listen["due"] > 0.8
    listen = B.listen_probs(p(rule={"task": 0.02}, hit={"hit": 0.95}, ask={"asks": 0.0}, listen={"fits": 0.5, "quiet": 0.5}))
    assert listen["due"] < 0.05                                 # "yes, it came up" alone, with no task set, is not due


async def test_bailian_takes_the_turn_at_its_own_line_not_by_a_draw():
    from jev_interaction import Config
    assert Config(judge_provider="bailian").policies["end_of_turn"].default == 0.725 == Config(judge_provider="bailian").finished_line()
    assert Config().policies["end_of_turn"].default == 0.5
    for p, taken in ((0.55, False), (0.8, True)):              # 0.55: this judge on a sentence cut off mid-thought
        done = {"finished": p, "continuing": 1 - p}
        s, events, judge = scripted_session(both_ways({**TURN, "done": done, "done_again": done,
                                                       "rule": {"task": 0.0, "no_task": 1.0}}), judge_provider="bailian")
        await s.on_segment(Segment("My order number is"))
        await asyncio.sleep(0.05)
        assert s.judged["finished"] == p and s.judged["go"] is taken     # the number as it comes, against 0.725
        s.silence_ms = 200
        await s.tick()
        assert any(e.get("what") == "end_of_turn" and e["go"] for e in events) is taken


async def test_bailian_floor_points_at_the_words_said_over_the_line():
    s, events, judge = make(both_ways({"floor": {"carry_on": 0.2, "yield": 0.1, "finish_first": 0.7}}))
    s.cfg.judge_provider = "bailian"
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    await s.on_segment(Segment("Who were you with?"))
    await asyncio.sleep(0.05)
    asked, state = judge.asked[0]
    assert asked == {"floor", "floor__r"} and state["user_words_over_it"] == "Who were you with?"
    assert state["agent_line"] == "So the thing about my morning is" and "Phone call" in state["call"]
    assert any(e.get("what") == "floor" and e["action"] == "finish_first" for e in events)


async def test_a_quiet_is_asked_as_small_facts_about_fields_of_their_own_whatever_the_judge():
    small = {"turn": {"theirs": 0.2, "ours": 0.8}, "busy": {"busy": 0.0, "not_busy": 1.0},
             "bye": {"goodbye": 0.95, "going": 0.05}, "gone": {"unanswered": 0.1, "not_yet": 0.9}}
    s, events, judge = make(both_ways(small))
    s.ledger.user("Okay, bye then")
    s.ledger.agent("Bye, take care.")
    s.spoke_into_quiet = 1
    await s.ask_quiet(30.0)
    asked, state = judge.asked[0]
    assert asked == {"turn", "busy", "bye", "gone", "turn__r", "busy__r", "bye__r", "gone__r"}    # how long: the engine's clock
    assert state["user_last_words"] == "Okay, bye then" and state["agent_last_line"] == "Bye, take care."
    assert any(e.get("what") == "quiet" and e["action"] == "hang_up" for e in events)


async def test_bailian_turn_uses_the_last_words_wording_and_asks_what_was_set_up_earlier():
    s, events, judge = make(both_ways({**TURN, "done_again": TURN["done"], "rule": {"task": 0.0, "no_task": 1.0}}))
    s.cfg.judge_provider = "bailian"                           # turn_question left at "engine": the provider decides
    s.ledger.user("Let me tell you about today")
    s.ledger.agent("Okay.")
    await s.on_segment(Segment("I had an interview"))
    await asyncio.sleep(0.05)
    asked, state = judge.asked[0]
    assert {"done", "done_again", "listen", "rule", "hit", "ask", "rule__r"} <= asked
    assert state["user_latest_words"] == "I had an interview" and state["user_earlier_lines"] == ["Let me tell you about today"]
