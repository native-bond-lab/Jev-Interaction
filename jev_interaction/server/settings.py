"""Settings for a local deployment: every node's provider and key, edited from the page and saved to .env.

GET  /api/settings          the setup steps (judge, language model, recognition, synthesis): each step's providers, their
                            fields and what is still missing; secrets come back only as set / not set. Plus reference
                            setups (what we run) to copy from, never applied unless asked.
POST /api/settings          {"values": {NAME: value}} -> written to .env (0600) and applied to this process at once
POST /api/settings/test     {"node": "judge" | "llm" | "asr" | "tts"} -> a live call with the saved values
POST /api/settings/detect   {"node": "llm" | "asr" | "tts", "key": "..."} -> whose key it looks like (nothing is sent)
POST /api/settings/models   {"base_url": "...", "key"?: "..."} -> the endpoint's own model list (GET {base_url}/models)

Writes are accepted only from this machine (localhost), unless SETTINGS_WRITABLE=1 (Docker, where the browser on the host
reaches the container through the bridge; docker-compose binds the port to 127.0.0.1 for that reason).
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import time

from jev_interaction.server import paths

ENV_FILE: pathlib.Path | None = None     # tests point this at a temporary file; otherwise the working folder's .env


def env_path() -> pathlib.Path:
    return ENV_FILE or paths.env_file()


# Reference setups: what we run, offered to copy from and never applied by default. .env.example carries the same
# values as comments; a test keeps them in step.
REFERENCES = [
    {"id": "global", "title": "What we run in production", "title_zh": "我们生产环境在用的组合",
     "note": "xAI grok-4.3 with reasoning off, ElevenLabs Scribe v2 realtime and eleven_v4_turbo. Keys: Jev, xAI, ElevenLabs.",
     "note_zh": "xAI grok-4.3（关闭思考）、ElevenLabs Scribe v2 实时识别和 eleven_v4_turbo 合成。需要 Jev、xAI、ElevenLabs 三把密钥。"},
    {"id": "china", "title": "A mainland China setup", "title_zh": "中国大陆可用的组合",
     "note": "Qwen, Paraformer and CosyVoice on Alibaba Cloud Bailian. Keys: Jev and one DashScope key.",
     "note_zh": "阿里云百炼上的通义千问、Paraformer 和 CosyVoice。需要 Jev 和一把百炼密钥。"},
]
TEMPLATES = {
    "global": {"JEV_MODEL": "jev-latest", "LLM_BASE_URL": "https://api.x.ai/v1", "LLM_MODEL": "grok-4.3", "LLM_TEMPERATURE": "0.7",
               "ASR_PROVIDER": "elevenlabs", "TTS_PROVIDER": "elevenlabs", "ELEVENLABS_ASR_MODEL": "scribe_v3_live",
               "ELEVENLABS_TTS_MODEL": "eleven_v4_turbo", "JEV_PRESET": "production"},
    "china": {"JEV_MODEL": "jev-latest", "LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1", "LLM_MODEL": "qwen-plus",
              "ASR_PROVIDER": "dashscope", "TTS_PROVIDER": "dashscope", "DASHSCOPE_ASR_MODEL": "paraformer-realtime-v2",
              "DASHSCOPE_TTS_MODEL": "cosyvoice-v2", "DASHSCOPE_TTS_VOICE": "longxiaochun_v2", "JEV_PRESET": "production"},
}

from jev_interaction.adapters import registry as R  # noqa: E402

for _r in REFERENCES:
    _r["values"] = TEMPLATES[_r["id"]]

TIMING = {"id": "timing", "title": "Timing preset", "title_zh": "时间参数预设", "fields": [
    {"name": "JEV_PRESET", "label": "Preset", "label_zh": "预设", "default": "production", "options": ["production", "tested", "default"]}]}


def build_nodes() -> list[dict]:
    """One card per pipeline node, from the provider registry (a provider registered by a plugin shows up here too)."""
    nodes = []
    for kind, (title, title_zh) in R.KINDS.items():
        fields: list[dict] = []
        provs = R.providers(kind)
        if kind in R.SELECTOR:
            fields.append({"name": R.SELECTOR[kind], "label": "Provider", "label_zh": "服务商", "default": "",
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


def _field(st) -> dict:
    out = st.card()
    current = os.getenv(st.name, "")
    if st.secret:
        out["set"] = bool(current)
    else:
        out["value"] = current
        if st.default:
            out["default"] = st.default
    if st.required and (st.required() if callable(st.required) else True):
        out["required"] = True
    return out


def steps() -> list[dict]:
    """One step per node, in pipeline order. `selected` is the chosen provider (None: the user has not chosen one)."""
    out = []
    for kind, (title, title_zh) in R.KINDS.items():
        chosen = R.selected(kind)
        provs = []
        for p in R.providers(kind):
            card = {"name": p.name, "label": p.label, "fields": [_field(st) for st in p.settings], "missing": p.missing()}
            if p.docs:
                card["docs"] = p.docs
            if kind == "tts":
                card["speech"] = R.speech_style(p.name)
            provs.append(card)
        step = {"id": kind, "title": title, "title_zh": title_zh, "selected": chosen, "providers": provs}
        if kind in R.SELECTOR:
            step["selector"] = R.SELECTOR[kind]
        if kind == "llm":
            step["vendors"] = [v.card() for v in R.LLM_VENDORS]
        mine = next((c for c in provs if c["name"] == chosen), None)
        step["ready"] = bool(mine) and not mine["missing"]
        out.append(step)
    return out


def read(client_host: str | None, host_header: str = "", origin: str = "") -> dict:
    st = steps()
    timing = {**TIMING, "fields": [{**f, "value": os.getenv(f["name"], "") or f["default"]} for f in TIMING["fields"]]}
    return {"writable": is_writable(client_host, host_header, origin), "env_file": str(env_path()),
            "ready": all(s["ready"] for s in st), "missing": R.missing_settings(), "steps": st,
            "references": REFERENCES, "timing": timing}


async def models(base_url: str, key: str | None = None) -> dict:
    """The model ids an OpenAI-compatible endpoint lists. Without a key, the saved one is used only for the saved
    endpoint (a saved key is never sent to a different host)."""
    import httpx
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        return {"ok": False, "error": "base_url must start with http:// or https://"}
    if not key and _host_only(base_url) == _host_only(os.getenv("LLM_BASE_URL", "")):
        key = os.getenv("LLM_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"} if key else {})
        if r.status_code != 200:
            return {"ok": False, "error": f"{r.status_code}: {r.text[:160]}"}
        data = r.json()
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        ids = sorted({(m.get("id") or m.get("name")) if isinstance(m, dict) else str(m) for m in items} - {None})
        return {"ok": True, "models": ids}
    except Exception as exc:  # noqa: BLE001 - reported to the page
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def write(values: dict[str, str]) -> None:
    """Set each NAME=value in .env (keeping comments and other lines) and in this process's environment."""
    unknown = sorted(set(values) - NAMES)
    if unknown:
        raise KeyError(f"unknown settings: {', '.join(unknown)}")
    clean = {k: str(v).strip().replace("\n", "") for k, v in values.items()}
    f = env_path()
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    done = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in clean:
                lines[i] = f"{k}={clean[k]}"
                done.add(k)
    lines += [f"{k}={v}" for k, v in clean.items() if k not in done]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        f.chmod(0o600)
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
            if R.selected("asr") == "elevenlabs":
                import httpx  # the realtime socket accepts a bad key at connect time: check the key itself
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
