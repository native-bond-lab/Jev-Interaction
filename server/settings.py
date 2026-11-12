"""Settings for a local deployment: every node's provider and key, edited from the page and saved to .env.

GET  /api/settings        what each node uses; secrets come back only as set / not set
POST /api/settings        {"values": {NAME: value}} -> written to .env (0600) and applied to this process at once
POST /api/settings/test   {"node": "judge" | "llm" | "asr" | "tts"} -> a live call with the saved values

Writes are accepted only from this machine (localhost), unless SETTINGS_WRITABLE=1 (Docker, where the browser on the host
reaches the container through the bridge; docker-compose binds the port to 127.0.0.1 for that reason).
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

from jev_interaction.adapters import registry as R  # noqa: E402

TIMING = {"id": "timing", "title": "Timing preset", "title_zh": "时间参数预设", "fields": [
    {"name": "JEV_PRESET", "label": "Preset", "label_zh": "预设", "default": "production", "options": ["production", "tested", "default"]}]}


def build_nodes() -> list[dict]:
    """One card per pipeline node, from the provider registry (a provider registered by a plugin shows up here too)."""
    nodes = []
    for kind, (title, title_zh) in R.KINDS.items():
        fields: list[dict] = []
        provs = R.providers(kind)
        if kind in R.SELECTOR:
            fields.append({"name": R.SELECTOR[kind], "label": "Provider", "label_zh": "服务商", "default": R.DEFAULT[kind],
                           "options": [p.name for p in provs]})
        for p in provs:
            for st in p.settings:
                f = {**st.card(), "default": st.default}
                if kind in R.SELECTOR:
                    f["provider"] = p.name
                fields.append(f)
        nodes.append({"id": kind, "title": title, "title_zh": title_zh, "fields": fields})
    return nodes + [TIMING]


NODES = build_nodes()
NAMES = {f["name"] for n in NODES for f in n["fields"]}
SECRETS = {f["name"] for n in NODES for f in n["fields"] if f.get("secret")}


def parse_env(path: pathlib.Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def templates() -> dict[str, dict[str, str]]:
    """The non-secret values of the two shipped templates, for the page's quick-fill buttons."""
    pick = lambda d: {k: v for k, v in d.items() if k in NAMES and k not in SECRETS and v}  # noqa: E731
    return {"global": pick(parse_env(ROOT / ".env.example")), "china": pick(parse_env(ROOT / ".env.china.example"))}


LOOPBACK = ("127.0.0.1", "::1", "localhost")


def _host_only(value: str) -> str:
    """'localhost:8080' / '[::1]:8080' / 'http://127.0.0.1:8080' -> the bare host."""
    from urllib.parse import urlparse
    value = value.strip()
    host = urlparse(value if "://" in value else f"//{value}").hostname or ""
    return host.strip("[]").lower()


def is_writable(client_host: str | None, host_header: str = "", origin: str = "") -> bool:
    """Writes come only from a page served by this server on this machine.

    Client address on loopback (or SETTINGS_WRITABLE=1 for Docker), the Host header naming loopback (against DNS
    rebinding: a remote page that resolves its own name to 127.0.0.1 still sends its own name as Host), and the Origin,
    when the browser sends one, being that same host (against any other site posting to localhost)."""
    if os.getenv("SETTINGS_WRITABLE") != "1" and (client_host or "") not in LOOPBACK:
        return False
    if host_header and _host_only(host_header) not in LOOPBACK:
        return False
    if origin and _host_only(origin) != _host_only(host_header or "localhost"):
        return False
    return True


def read(client_host: str | None, host_header: str = "", origin: str = "") -> dict:
    nodes = []
    for node in NODES:
        fields = []
        for f in node["fields"]:
            out = {k: v for k, v in f.items() if k != "default"}
            current = os.getenv(f["name"], "")
            if f.get("secret"):
                out["set"] = bool(current)
            else:
                out["value"] = current or f.get("default", "")
            fields.append(out)
        nodes.append({**node, "fields": fields})
    return {"writable": is_writable(client_host, host_header, origin), "env_file": ENV_FILE.name, "nodes": nodes, "templates": templates()}


def write(values: dict[str, str]) -> None:
    """Set each NAME=value in .env (keeping comments and other lines) and in this process's environment."""
    unknown = sorted(set(values) - NAMES)
    if unknown:
        raise KeyError(f"unknown settings: {', '.join(unknown)}")
    clean = {k: str(v).strip().replace("\n", "") for k, v in values.items()}
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    done = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in clean:
                lines[i] = f"{k}={clean[k]}"
                done.add(k)
    lines += [f"{k}={v}" for k, v in clean.items() if k not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    for k, v in clean.items():
        os.environ[k] = v


async def test(node: str, make_recognizer, make_synthesizer) -> dict:
    """One live call to the node's provider with the saved settings."""
    from jev_interaction import Profile
    started = time.monotonic()
    try:
        if node == "judge":
            client = R.create("judge")
            try:
                await asyncio.wait_for(client.ask({"ok": {"type": "choice", "instructions": "Is this a connection test?",
                                                          "criteria": {"yes": "it is", "no": "it is not"}}}, "A connection test."), 15)
            finally:
                await client.aclose()
        elif node == "llm":
            async def first_line():
                async for _ in R.create("llm").lines([{"role": "user", "content": "Say hi in two words."}], 16):
                    return
            await asyncio.wait_for(first_line(), 20)
        elif node == "tts":
            async def first_chunk():
                async for _ in make_synthesizer(Profile(name="test")).audio("Hi."):
                    return
            await asyncio.wait_for(first_chunk(), 20)
        elif node == "asr":
            if os.getenv("ASR_PROVIDER", "elevenlabs").lower() == "elevenlabs":
                import httpx    # the realtime socket accepts a bad key at connect time: check the key itself
                async with httpx.AsyncClient(timeout=15) as http:
                    r = await http.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": os.getenv("ELEVENLABS_API_KEY", "")})
                    if r.status_code != 200:
                        raise RuntimeError(f"elevenlabs {r.status_code}: {r.text[:120]}")
            rec = make_recognizer(os.getenv("TEST_LANGUAGE", "en"))
            await asyncio.wait_for(rec.connect(), 15)
            await rec.close()
        else:
            return {"ok": False, "error": f"unknown node {node!r}"}
    except Exception as exc:  # noqa: BLE001 - reported to the page, never raised
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"ok": True, "ms": int((time.monotonic() - started) * 1000)}
