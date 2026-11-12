"""The `jev-interaction` command.

    jev-interaction serve [--host 127.0.0.1] [--port 8080] [--preset production] [--home .]
    jev-interaction init [--reference global|china]   write .env (empty, or a reference setup's values) and profiles/
    jev-interaction replay runs/*.jsonl --purpose floor [--edit my_questions.py]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys


def _serve(a: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print('The server needs its extras:  pip install "jev-interaction[server]"', file=sys.stderr)
        return 1
    if a.home:
        os.environ["JEV_HOME"] = str(pathlib.Path(a.home).resolve())
    if a.preset:
        os.environ["JEV_PRESET"] = a.preset
    from jev_interaction.server import paths
    if not paths.env_file().exists():
        print(f"No .env in {paths.home()} yet: the page walks you through the providers and keys.")
    print(f"Jev-Interaction on http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}")
    uvicorn.run("jev_interaction.server.app:app", host=a.host, port=a.port, log_level="warning" if a.quiet else "info")
    return 0


def _init(a: argparse.Namespace) -> int:
    from jev_interaction.server import paths, settings
    home = pathlib.Path(a.home or os.getcwd()).resolve()
    os.environ["JEV_HOME"] = str(home)
    env = paths.env_file()
    if env.exists():
        print(f"{env} already exists; leaving it alone.")
    else:
        t = settings.TEMPLATES[a.reference] if a.reference else {}
        keys = sorted(settings.SECRETS)
        body = ["# Jev-Interaction settings. Fill them in here, or follow the setup steps on the page."]
        body += [f"{k}=" for k in keys] + [f"{k}={v}" for k, v in t.items()]
        env.write_text("\n".join(body) + "\n", encoding="utf-8")
        env.chmod(0o600)
        print(f"Wrote {env}")
    (home / "profiles").mkdir(exist_ok=True)
    print(f"Your own personas go in {home / 'profiles'} (copy one from {paths.PACKAGE / 'profiles'} to start).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jev-interaction", description="Full-duplex voice calls, turn-taking judged by Jev.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the call server and its page")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")))
    s.add_argument("--preset", help="production | tested | default (overrides JEV_PRESET)")
    s.add_argument("--home", help="working folder for .env, runs/ and profiles/ (default: here)")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(run=_serve)
    i = sub.add_parser("init", help="write a .env template and a profiles/ folder")
    i.add_argument("--reference", choices=["global", "china"], help="start from a reference setup (what we run / mainland China)")
    i.add_argument("--home")
    i.set_defaults(run=_init)
    r = sub.add_parser("replay", help="re-ask the decisions recorded in call logs, as asked or reworded")
    from jev_interaction import replay as R
    R.add_arguments(r)
    r.set_defaults(run=lambda a: __import__("asyncio").run(R.run(a)))
    a = ap.parse_args(argv)
    return a.run(a)


if __name__ == "__main__":
    sys.exit(main())
