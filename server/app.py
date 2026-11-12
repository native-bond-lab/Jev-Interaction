"""A runnable call server: one WebSocket per call, one HTTP route for line audio, a few JSON routes for the page.

    ./scripts/setup.sh            (or: pip install -e ".[server]"; cp .env.example .env; fill in the keys)
    uvicorn server.app:app --port 8080     then open http://localhost:8080

WebSocket /ws: first message {"type": "start", "profile": "examples/profiles/companion.yaml", "language": "en"}, then binary
200 ms PCM16 16 kHz frames and JSON client messages; events come back as JSON.

Providers come from the environment: ASR_PROVIDER / TTS_PROVIDER = elevenlabs (default) or dashscope (mainland China),
any OpenAI-compatible LLM (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), and JEV_PRESET = production (default) | tested | default.
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict
import pathlib
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

ROOT = pathlib.Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from jev_interaction import Profile  # noqa: E402  (after .env, so adapters read the keys)
from jev_interaction.adapters import EnergyVAD  # noqa: E402
from jev_interaction.adapters.openai_compat import OpenAICompatResponder  # noqa: E402
from jev_interaction.judge import JevClient  # noqa: E402
from jev_interaction.presets import config as preset_config  # noqa: E402
from jev_interaction.recorder import Recorder  # noqa: E402
from jev_interaction.session import Session  # noqa: E402
from server import settings as S  # noqa: E402

WEB = ROOT / "web"
PROFILES = ROOT / "examples" / "profiles"
app = FastAPI(title="Jev-Interaction")
LINES: "OrderedDict[str, tuple[str, object]]" = OrderedDict()   # line id -> (text, synthesizer); the newest MAX_LINES
MAX_LINES = 2000
MAX_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "0"))     # 0 = no limit; set it for a public demo (e.g. a HF Space)
MAX_CALL_S = float(os.getenv("MAX_CALL_SECONDS", "0"))      # 0 = no limit
ACTIVE = {"calls": 0}


def asr_provider() -> str:
    return os.getenv("ASR_PROVIDER", "elevenlabs").lower()


def tts_provider() -> str:
    return os.getenv("TTS_PROVIDER", "elevenlabs").lower()


def make_recognizer(language: str):
    if asr_provider() == "dashscope":
        from jev_interaction.adapters.dashscope_asr import ParaformerRealtime
        return ParaformerRealtime(language=language)
    from jev_interaction.adapters.scribe import ScribeRealtime
    return ScribeRealtime(language=language)


def make_synthesizer(profile: Profile):
    voices = profile.extra.get("voices") or {}
    if tts_provider() == "dashscope":
        from jev_interaction.adapters.dashscope_tts import CosyVoiceTTS
        return CosyVoiceTTS(voice=voices.get("dashscope"))
    from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
    return ElevenLabsTTS(voice_id=voices.get("elevenlabs"))


def profile_card(path: pathlib.Path) -> dict:
    p = Profile.load(path)
    d = p.extra.get("display") or {}
    return {"id": path.stem, "path": str(path.relative_to(ROOT)), "name": p.name, "title": d.get("title", p.name),
            "title_zh": d.get("title_zh", d.get("title", p.name)), "tagline": d.get("tagline", p.task),
            "tagline_zh": d.get("tagline_zh", d.get("tagline", p.task)), "language": d.get("language", "en"),
            "accent": d.get("accent", "#3ee0c8"), "order": d.get("order", 100)}


@app.get("/api/profiles")
def profiles():
    cards = [profile_card(f) for f in sorted(PROFILES.glob("*.yaml"))]
    return sorted(cards, key=lambda c: (c["order"], c["id"]))


@app.get("/api/health")
def health():
    need = ["JEV_API_KEY"]
    local_llm = any(h in os.getenv("LLM_BASE_URL", "") for h in ("localhost", "127.0.0.1", "0.0.0.0"))
    if not local_llm:
        need.append("LLM_API_KEY")
    if "elevenlabs" in (asr_provider(), tts_provider()):
        need.append("ELEVENLABS_API_KEY")
    if tts_provider() == "elevenlabs":
        need.append("ELEVENLABS_VOICE_ID")
    if "dashscope" in (asr_provider(), tts_provider()):
        need.append("DASHSCOPE_API_KEY")
    missing = [k for k in need if not os.getenv(k)]
    return {"ready": not missing, "missing": missing, "preset": os.getenv("JEV_PRESET", "production"),
            "providers": {"llm": f"{os.getenv('LLM_MODEL', 'grok-4.3')} @ {os.getenv('LLM_BASE_URL', 'https://api.x.ai/v1')}",
                          "asr": asr_provider(), "tts": tts_provider(), "judge": os.getenv("JEV_MODEL", "jev-latest")}}


def _who(request) -> tuple[str | None, str, str]:
    return (request.client.host if request.client else None, request.headers.get("host", ""), request.headers.get("origin", ""))


async def _local_json(request: Request) -> dict:
    """The body of a settings request that really comes from this server's own page on this machine."""
    if not S.is_writable(*_who(request)):
        raise HTTPException(403, "Settings can only be changed from this server's page, on the machine running it.")
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Send JSON.")      # a cross-site form or text/plain post is refused before it is read
    return await request.json()


@app.get("/api/settings")
def get_settings(request: Request):
    return S.read(*_who(request))


@app.post("/api/settings")
async def save_settings(request: Request):
    body = await _local_json(request)
    try:
        S.write(body.get("values") or {})
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "health": health()}


@app.post("/api/settings/test")
async def test_settings(request: Request):
    body = await _local_json(request)
    return await S.test(body.get("node", ""), make_recognizer, make_synthesizer)


@app.get("/tts/{line_id}")
async def tts(line_id: str):
    found = LINES.get(line_id)
    if found is None:
        raise HTTPException(404)
    text, synth = found
    return StreamingResponse(synth.audio(text), media_type=synth.media_type)


def same_origin(origin: str, host: str) -> bool:
    """A call may be opened only by this server's own page (or an origin listed in ALLOWED_ORIGINS): any other site
    could otherwise open a billed call through the visitor's browser."""
    if not origin:
        return True
    allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return S._host_only(origin) == S._host_only(host) or origin in allowed


@app.websocket("/ws")
async def call(ws: WebSocket):
    if not same_origin(ws.headers.get("origin", ""), ws.headers.get("host", "")):
        await ws.close(code=4403)
        return
    await ws.accept()
    if MAX_CALLS and ACTIVE["calls"] >= MAX_CALLS:
        await ws.send_text(json.dumps({"type": "busy", "text": "All lines are busy, try again in a minute."}))
        await ws.close(code=4429)
        return
    start = json.loads(await ws.receive_text())
    path = (ROOT / start.get("profile", "examples/profiles/companion.yaml")).resolve()
    if PROFILES.resolve() not in path.parents or not path.exists():
        await ws.close(code=4404)
        return
    profile = Profile.load(path)
    language = start.get("language") or (profile.extra.get("display") or {}).get("language", "en")
    cfg = preset_config(os.getenv("JEV_PRESET", "production"), language=language)
    synth = make_synthesizer(profile)

    async def send(event: dict):
        if event.get("type") in ("line", "listen"):
            LINES[event["id"]] = (event["text"], synth)
            while len(LINES) > MAX_LINES:
                LINES.popitem(last=False)
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    judge = JevClient()
    session = Session(profile, send=send, judge=judge, recognizer=make_recognizer(language),
                      responder=OpenAICompatResponder(), vad=EnergyVAD(), config=cfg,
                      recorder=Recorder(ROOT / "runs" / f"call-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    ACTIVE["calls"] += 1
    started = time.monotonic()
    try:
        try:
            await session.start()
        except Exception as exc:  # noqa: BLE001 - e.g. the recognizer refused the key: tell the page, end the call
            await ws.send_text(json.dumps({"type": "error", "what": "start", "text": f"{type(exc).__name__}: {str(exc)[:160]}"}))
            return
        while True:
            if MAX_CALL_S and time.monotonic() - started > MAX_CALL_S:
                await ws.send_text(json.dumps({"type": "hangup", "why": "time limit"}))
                break
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await session.on_audio(msg["bytes"])
            elif msg.get("text"):
                await session.on_client(json.loads(msg["text"]))
    except WebSocketDisconnect:
        pass
    finally:
        ACTIVE["calls"] -= 1
        try:
            await session.close()
        finally:
            await judge.aclose()


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/{name:path}")
def web_file(name: str):
    """Everything else the page asks for comes from web/ (scripts, styles, images), never from outside it."""
    path = (WEB / name).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
