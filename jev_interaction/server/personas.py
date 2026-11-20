"""Make and change personas from the page.

A persona is a YAML file (jev_interaction/profile.py). The page edits the parts a person writes: the name and card,
`prompt` (what the language model is told about who it is and how it talks), `manner` (what Jev is told about how it
behaves on a call), `turn_taking` (its thresholds and timing) and its voice for the synthesizer in use. Everything
else in the file (policies, a cast, other voices) is kept as it was.

Files are written only to the working folder's profiles/ (paths.home()), and only from this server's own page on this
machine (settings.is_writable), as the settings are: a public deployment lists its personas and never offers to edit
them. Saving a built-in persona writes your copy under the same id, which replaces the built-in one for you; deleting
your copy brings the built-in one back.
"""
from __future__ import annotations

import re

import yaml

from jev_interaction.profile import Profile, TurnTaking

from . import paths

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
TEXT_MAX = {"name": 80, "title": 60, "tagline": 160, "prompt": 6000, "manner": 3000, "voice": 120}
LANGUAGES = ("en", "zh")


def own_dir():
    return paths.home() / "profiles"


def is_own(pid: str) -> bool:
    """The persona's file is one of yours (the working folder's profiles/), not a built-in one."""
    f = paths.profiles().get(pid)
    return f is not None and f.parent.resolve() == own_dir().resolve()


def read(pid: str, tts: str | None) -> dict:
    """What the editor shows for one persona. KeyError when there is none by that id."""
    f = paths.profiles()[pid]
    p = Profile.load(f)
    d = p.extra.get("display") or {}
    t = p.turn_taking
    return {"id": pid, "own": is_own(pid), "builtin": (paths.PACKAGE / "profiles" / f"{pid}.yaml").exists(),
            "name": p.name, "language": d.get("language", "en"), "title": d.get("title", ""), "tagline": d.get("tagline", ""),
            "accent": d.get("accent", "#3ee0c8"), "prompt": p.prompt, "manner": p.manner,
            "turn_taking": {"yield_shift": t.yield_shift, "cut_in": t.cut_in, "lead_scale": t.lead_scale},
            "voice": (p.extra.get("voices") or {}).get(tts or "", "")}


def new_id(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40] or "persona"
    pid, n = base, 2
    while pid in paths.profiles():
        pid, n = f"{base}_{n}", n + 1
    return pid


def _text(body: dict, key: str) -> str:
    v = body.get(key, "")
    if not isinstance(v, str):
        raise ValueError(f"{key} must be text")
    v = v.strip()
    if len(v) > TEXT_MAX[key]:
        raise ValueError(f"{key} is longer than {TEXT_MAX[key]} characters")
    return v


def save(body: dict, tts: str | None) -> str:
    """Write a persona from the editor's fields; returns its id. A body without an id makes a new persona."""
    pid = str(body.get("id") or "").strip() or new_id(str(body.get("name") or ""))
    if not ID.match(pid):
        raise ValueError("id: lowercase letters, digits, - and _ only")
    name = _text(body, "name")
    if not name:
        raise ValueError("name is required")
    language = body.get("language") or "en"
    if language not in LANGUAGES:
        raise ValueError(f"language is one of {', '.join(LANGUAGES)}")
    accent = str(body.get("accent") or "#3ee0c8")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        raise ValueError("accent is a colour like #3ee0c8")
    tt = body.get("turn_taking") or {}
    try:
        turn = TurnTaking(yield_shift=float(tt.get("yield_shift", 0.0)), cut_in=str(tt.get("cut_in", "pace")),
                          lead_scale=float(tt.get("lead_scale", 1.0)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"turn_taking: {exc}") from exc
    if not -0.5 <= turn.yield_shift <= 0.5 or not 0.25 <= turn.lead_scale <= 4:
        raise ValueError("turn_taking: yield_shift within -0.5 .. 0.5, lead_scale within 0.25 .. 4")

    existing = paths.profiles().get(pid)                     # yours or the built-in one: keep what the editor does not show
    if existing is not None and existing.parent.resolve() not in (own_dir().resolve(), (paths.PACKAGE / "profiles").resolve()):
        raise ValueError(f"{pid} is read from {existing.parent} (JEV_PROFILES_DIR): edit the file there")
    d = yaml.safe_load(existing.read_text(encoding="utf-8")) if existing else {}
    d = d if isinstance(d, dict) else {}
    d["name"] = name
    d["prompt"] = _text(body, "prompt")
    d["manner"] = _text(body, "manner")
    d["turn_taking"] = {"yield_shift": turn.yield_shift, "cut_in": turn.cut_in, "lead_scale": turn.lead_scale}
    voice = _text(body, "voice")
    voices = dict(d.get("voices") or {})
    if tts:
        if voice:
            voices[tts] = voice
        else:
            voices.pop(tts, None)
    if voices:
        d["voices"] = voices
    else:
        d.pop("voices", None)
    display = dict(d.get("display") or {})
    display.update({"title": _text(body, "title") or name, "tagline": _text(body, "tagline"), "language": language,
                    "accent": accent, "listed": True})
    display.setdefault("group", "task")
    for key in ("title_zh", "tagline_zh"):                  # one text per field now: the page shows what was typed
        display.pop(key, None)
    d["display"] = display

    Profile(name=name, prompt=d["prompt"], manner=d["manner"], turn_taking=turn)   # the engine can read what is written
    own_dir().mkdir(parents=True, exist_ok=True)
    target = own_dir() / f"{pid}.yaml"
    head = "# Written from the Jev-Interaction page. Keys the page does not edit are kept as they were.\n"
    target.write_text(head + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return pid


def delete(pid: str) -> bool:
    """Remove your copy of a persona. False when the persona is not one of yours (a built-in one is never deleted)."""
    if not ID.match(pid) or not is_own(pid):
        return False
    (own_dir() / f"{pid}.yaml").unlink()
    return True
