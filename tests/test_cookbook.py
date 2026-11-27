"""The cookbook says what the code does: its setups, field names and example profiles are checked here."""
import dataclasses
import pathlib
import re
import warnings

from jev_interaction import Config, Profile
from jev_interaction.config import barge_stop_after_ms, turn_cap_after_ms
from jev_interaction.server import settings as S

ROOT = pathlib.Path(__file__).resolve().parents[1]
BOOK = ROOT / "cookbook"


def test_recommended_stacks_match_the_setup_page():
    text = (BOOK / "stacks.md").read_text(encoding="utf-8")
    for values in S.TEMPLATES.values():
        for k, v in values.items():
            if k not in ("JEV_MODEL", "JEV_PRESET"):
                assert re.search(rf"^{k}={re.escape(v)}\b", text, re.M), (k, v)
    for k in set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, re.M)):
        assert k in S.NAMES or k.startswith(("MAX_", "TTS_VOICES", "HTTPS_PROXY", "JEV_RECORD", "LLM_EXTRA")), k


def test_every_field_the_parameters_page_names_exists_and_every_timing_field_is_there():
    text = (BOOK / "parameters.md").read_text(encoding="utf-8")
    fields = {f.name for f in dataclasses.fields(Config)}
    named = {n for n in re.findall(r"^\| `(\w+)`", text, re.M)} - {"recommended", "tested", "default", "normal",
                                                                     "patient", "narrate", "eager"}
    named |= {n for row in re.findall(r"^\| `(\w+)` / `(\w+)`", text, re.M) for n in row}
    assert named <= fields, named - fields
    plumbing = {"language", "frame_ms", "sample_rate", "paces", "start_pace", "opening_turns", "policies", "hold_after_ms", "hold_release_ms"}
    assert fields - plumbing <= named, (fields - plumbing) - named


def test_voice_timing_overrides_keep_the_public_config_fields_stable(monkeypatch):
    monkeypatch.setenv("JEV_BARGE_STOP_MS", "900")
    monkeypatch.setenv("JEV_TURN_CAP_MS", "3600")
    assert barge_stop_after_ms() == 900
    assert turn_cap_after_ms(Config().pace("normal"), 4000) == 3600
    assert not hasattr(Config(), "barge_stop_ms") and not hasattr(Config(), "turn_cap_ms")


def test_cookbook_profiles_load_with_a_card_and_their_cast_is_there():
    files = {f.stem: f for f in (BOOK / "profiles").glob("*.yaml")}
    assert files
    for f in files.values():
        p = Profile.load(f)
        d = p.extra.get("display") or {}
        assert p.name and p.manner and d.get("title") and d.get("title_zh") and d.get("language") in ("en", "zh"), f.name
        assert set(p.extra.get("cast") or []) <= set(files), f.name


def test_the_old_name_of_the_overlap_field_still_works():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = Config(hold_after_ms=1000)
    assert cfg.overlap_ask_ms == 1000 and cfg.hold_after_ms is None and w


def test_the_0_1_hold_release_is_accepted_and_an_explicit_overlap_wins():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert Config(hold_release_ms=700).hold_release_ms is None
        assert Config(hold_after_ms=600, overlap_ask_ms=1000).overlap_ask_ms == 1000


async def test_re_ask_marks_that_are_not_multiples_of_a_frame_still_fire():
    import asyncio
    import time

    from jev_interaction.decisions.turn import TURN
    from jev_interaction.policy import ThresholdPolicy
    from jev_interaction.testing import scripted_session
    from jev_interaction.utterance import Utterance
    s, _, judge = scripted_session({"done": {"finished": 0.2, "continuing": 0.8}}, turn_reask_ms=(500, 1500),
                                   policies={"end_of_turn": ThresholdPolicy(default=0.5)})   # not a draw: never answers here
    s.utt = Utterance(1, time.monotonic(), [(0.0, "and then, um,")])
    s.judged = {"finished": 0.2, "drawn": True}
    for ms in range(200, 1800, s.cfg.frame_ms):        # the quiet grows a frame at a time
        s.silence_ms = ms
        await TURN.on_tick(s, time.monotonic())
        await asyncio.gather(*list(s._tasks))       # each question answered before the quiet grows on
    assert len(judge.asked) == 2


def test_a_0_1_policies_dict_keeps_the_defaults_of_newer_decisions():
    from jev_interaction.policy import ThresholdPolicy
    from jev_interaction.session import Session
    from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeResponder, FakeVAD
    cfg = Config(policies={"end_of_turn": ThresholdPolicy(default=0.7)})
    s = Session(Profile("Sam"), send=None, judge=FakeJudge({}), recognizer=FakeRecognizer(), responder=FakeResponder(),
                vad=FakeVAD(), config=cfg)
    assert "who" in s.policies and "listen" in s.policies and s.policies["end_of_turn"].default == 0.7
