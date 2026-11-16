"""The cookbook says what the code does: its setups, field names and example profiles are checked here."""
import dataclasses
import pathlib
import re
import warnings

from jev_interaction import Config, Profile
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
    plumbing = {"language", "frame_ms", "sample_rate", "paces", "start_pace", "opening_turns", "policies", "hold_after_ms"}
    assert fields - plumbing <= named, (fields - plumbing) - named


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
