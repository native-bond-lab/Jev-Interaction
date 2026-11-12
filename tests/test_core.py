import asyncio
import pathlib

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
    assert set(Q.listen("Mara")["criteria"]) == {"continuer", "feeling", "echo", "quiet", "answer_due"}


from jev_interaction.testing import FakeASR, FakeJudge, FakeLLM, FakeVAD, scripted_session  # noqa: E402,F401


def make(answers, policies=None):
    return scripted_session(answers, policies)


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


async def test_a_failing_judge_never_leaves_the_line_held():
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
    assert s.held
    await s.on_segment(Segment("Wait, what?"))
    await asyncio.sleep(0.05)
    assert not s.held and any(e["type"] == "unhold" for e in events)
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


def test_provider_registry_drives_factories_health_and_settings(monkeypatch):
    from jev_interaction.adapters import registry as R
    for k in ("JEV_API_KEY", "LLM_API_KEY", "LLM_BASE_URL", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k in ("ASR_PROVIDER", "TTS_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert R.missing_settings() == ["JEV_API_KEY", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "ASR_PROVIDER", "TTS_PROVIDER"]
    monkeypatch.setenv("ASR_PROVIDER", "dashscope")                    # speech is never chosen for the user
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("LLM_MODEL", "llama3")
    assert R.missing_settings() == ["JEV_API_KEY", "LLM_BASE_URL", "LLM_API_KEY", "DASHSCOPE_API_KEY", "ELEVENLABS_API_KEY",
                                    "ELEVENLABS_VOICE_ID"]
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
