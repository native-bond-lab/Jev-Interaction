"""Making and changing personas from the page (server/personas.py): written to profiles/ in the working folder, only
from this machine, keeping what the editor does not show."""
import yaml
from fastapi.testclient import TestClient

from jev_interaction import Profile


def client(tmp_path, monkeypatch, writable=True):
    from jev_interaction.server import app as server
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    monkeypatch.delenv("JEV_PROFILES_DIR", raising=False)
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    if writable:
        monkeypatch.setenv("SETTINGS_WRITABLE", "1")             # the test client is not on loopback
    else:
        monkeypatch.delenv("SETTINGS_WRITABLE", raising=False)
    return TestClient(server.app, base_url="http://localhost")


NEW = {"name": "Rex Hale", "language": "en", "title": "Coach", "tagline": "Short and firm", "accent": "#ff8800",
       "prompt": "You are Rex, a blunt running coach.", "manner": "Cuts in when the runner makes excuses.",
       "turn_taking": {"yield_shift": 0.15, "cut_in": "always", "lead_scale": 0.6}, "voice": "voice123"}


def test_a_new_persona_is_written_to_your_profiles_and_listed(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/api/personas", json=NEW)
    assert r.status_code == 200 and r.json()["id"] == "rex_hale"
    p = Profile.load(tmp_path / "profiles" / "rex_hale.yaml")
    assert p.prompt == NEW["prompt"] and p.manner == NEW["manner"] and p.turn_taking.cut_in == "always"
    assert p.extra["voices"] == {"elevenlabs": "voice123"} and p.extra["display"]["accent"] == "#ff8800"
    card = next(x for x in c.get("/api/profiles").json() if x["id"] == "rex_hale")
    assert card["own"] and card["title"] == "Coach"
    got = c.get("/api/personas/rex_hale").json()
    assert got["own"] and not got["builtin"] and got["turn_taking"]["lead_scale"] == 0.6 and got["voice"] == "voice123"
    assert c.post("/api/personas", json=NEW).json()["id"] == "rex_hale_2"          # a second new one does not overwrite


def test_editing_a_built_in_persona_writes_your_copy_and_keeps_what_the_editor_does_not_show(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    lyra = c.get("/api/personas/lyra").json()
    assert not lyra["own"] and lyra["builtin"]
    assert c.post("/api/personas", json={**lyra, "prompt": "You are Lyra, shorter."}).status_code == 200
    mine = yaml.safe_load((tmp_path / "profiles" / "lyra.yaml").read_text(encoding="utf-8"))
    assert mine["prompt"] == "You are Lyra, shorter." and mine["cast"] == ["kai"] and "policies" in mine
    assert c.get("/api/personas/lyra").json()["own"]
    assert c.post("/api/personas/lyra/delete", json={}).status_code == 200            # back to the built-in one
    assert not (tmp_path / "profiles" / "lyra.yaml").exists() and not c.get("/api/personas/lyra").json()["own"]
    assert c.post("/api/personas/lyra/delete", json={}).status_code == 400            # a built-in file is never deleted


def test_personas_are_changed_only_from_this_machine_and_only_with_sound_values(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, writable=False)
    remote = TestClient(c.app, base_url="http://example.com")
    assert remote.post("/api/personas", json=NEW).status_code == 403
    assert remote.get("/api/personas/lyra").status_code == 200                       # reading is fine
    c = client(tmp_path, monkeypatch)
    for bad in ({"name": ""}, {"id": "../etc"}, {"accent": "red"}, {"language": "fr"},
                {"turn_taking": {"cut_in": "sometimes"}}, {"turn_taking": {"lead_scale": 0}}):
        assert c.post("/api/personas", json={**NEW, **bad}).status_code == 400, bad
    assert c.get("/api/personas/nobody").status_code == 404
    assert not (tmp_path / "profiles").exists() or not list((tmp_path / "profiles").glob("*.yaml"))
