"""Where the server finds things, the same for a clone and for `pip install`.

The working folder (JEV_HOME, default: where you start the server) holds your .env, call logs (runs/) and your own
personas (profiles/*.yaml). The page and the built-in personas ship inside the package; a persona of yours with the same
file name replaces the built-in one.
"""
from __future__ import annotations

import os
import pathlib

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
WEB = pathlib.Path(__file__).resolve().parent / "web"


def home() -> pathlib.Path:
    return pathlib.Path(os.getenv("JEV_HOME") or os.getcwd()).resolve()


def env_file() -> pathlib.Path:
    return home() / ".env"


def runs_dir() -> pathlib.Path:
    return pathlib.Path(os.getenv("JEV_RUNS_DIR") or home() / "runs")


def profile_dirs() -> list[pathlib.Path]:
    extra = [pathlib.Path(p) for p in os.getenv("JEV_PROFILES_DIR", "").split(os.pathsep) if p]
    return [*extra, home() / "profiles", PACKAGE / "profiles"]


def profiles() -> dict[str, pathlib.Path]:
    """Persona id (file name without .yaml) -> file; earlier folders win."""
    found: dict[str, pathlib.Path] = {}
    for d in profile_dirs():
        for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
            found.setdefault(f.stem, f)
    return found


def load_env() -> None:
    """Read the working folder's .env into the environment (values already set in the environment win)."""
    f = env_file()
    for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
