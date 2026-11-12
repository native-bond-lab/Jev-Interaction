"""A runnable call server: one WebSocket per call, one HTTP route for line audio, a few JSON routes for the page.

    pip install "jev-interaction[server]"; jev-interaction serve      then open http://localhost:8080
    (from a clone: ./scripts/setup.sh)

WebSocket /ws: first message {"type": "start", "profile": "companion", "language": "en"}, then binary 200 ms PCM16
16 kHz frames and JSON client messages; events come back as JSON. The protocol is in docs/protocol.md.

Providers come from the environment: ASR_PROVIDER / TTS_PROVIDER = elevenlabs (default) or dashscope (mainland China),
any OpenAI-compatible LLM (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL), and JEV_PRESET = production (default) | tested | default.
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from jev_interaction.server import paths

paths.load_env()

from jev_interaction import Profile  # noqa: E402  (after .env, so adapters read the keys)
from jev_interaction import preset as preset_config  # noqa: E402
from jev_interaction.adapters import EnergyVAD, registry  # noqa: E402
from jev_interaction.recorder import Recorder  # noqa: E402
from jev_interaction.server import settings as S  # noqa: E402
from jev_interaction.session import Session  # noqa: E402

WEB = paths.WEB
RECORD = os.getenv("JEV_RECORD_CALLS", "1") != "0"     # call logs in runs/ for replay; a public demo sets 0
app = FastAPI(title="Jev-Interaction")
LINES: OrderedDict[str, tuple[str, object]] = OrderedDict()   # line id -> (text, synthesizer); the newest MAX_LINES
MAX_LINES = 2000
MAX_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "0"))     # 0 = no limit; set it for a public demo (e.g. a HF Space)
MAX_CALL_S = float(os.getenv("MAX_CALL_SECONDS", "0"))      # 0 = no limit
DAY_BUDGET_S = 60 * float(os.getenv("MAX_CALL_MINUTES_PER_DAY", "0"))   # 0 = no limit; all calls together, per UTC day
ACTIVE = {"calls": 0}
SPENT = {"day": "", "seconds": 0.0}     # call time already used today (finished calls)


def spent_today() -> float:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if SPENT["day"] != day:
        SPENT.update(day=day, seconds=0.0)
    return SPENT["seconds"]


def make_recognizer(language: str):
    return registry.create("asr", language=language)


def voice_overrides() -> dict[str, str]:
    """TTS_VOICES="companion=<voice>,vera=<voice>": a voice per persona for this deployment (e.g. voices only your
    account has), over the persona file's own voice for the chosen provider."""
    pairs = (item.split("=", 1) for item in os.getenv("TTS_VOICES", "").split(",") if "=" in item)
    return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}


def make_synthesizer(profile: Profile, persona: str | None = None):
    voices = profile.extra.get("voices") or {}
    voice = voice_overrides().get(persona or "") or voices.get(registry.selected("tts"))
    return registry.create("tts", voice=voice)


def profile_card(pid: str, path) -> dict:
    p = Profile.load(path)
    d = p.extra.get("display") or {}
    return {"id": pid, "path": pid, "name": p.name, "title": d.get("title", p.name),
            "title_zh": d.get("title_zh", d.get("title", p.name)), "tagline": d.get("tagline", p.task),
            "tagline_zh": d.get("tagline_zh", d.get("tagline", p.task)), "language": d.get("language", "en"),
            "accent": d.get("accent", "#3ee0c8"), "order": d.get("order", 100),
            "group": d.get("group", "task")}


@app.get("/api/profiles")
def profiles():
    cards = [profile_card(pid, f) for pid, f in paths.profiles().items()]
    return sorted(cards, key=lambda c: (c["order"], c["id"]))


@app.get("/api/health")
def health():
    missing = registry.missing_settings()
    llm = f"{os.getenv('LLM_MODEL', '')} @ {os.getenv('LLM_BASE_URL', '')}" if os.getenv("LLM_BASE_URL") else None
    return {"ready": not missing, "missing": missing, "preset": os.getenv("JEV_PRESET", "production"),
            "providers": {"judge": os.getenv("JEV_MODEL", "jev-latest"), "llm": llm, "asr": registry.selected("asr"),
                          "tts": registry.selected("tts")}, "speech": registry.speech_style()}


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


@app.post("/api/settings/detect")
async def detect_key(request: Request):
    body = await _local_json(request)
    return {"candidates": registry.detect(str(body.get("node", "")), str(body.get("key", "")))}


@app.post("/api/settings/models")
async def list_models(request: Request):
    body = await _local_json(request)
    return await S.models(str(body.get("base_url", "")), body.get("key") or None)


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
    if DAY_BUDGET_S and spent_today() >= DAY_BUDGET_S:
        await ws.send_text(json.dumps({"type": "busy", "text": "Today's call minutes are used up. Come back tomorrow, or run it yourself."}))
        await ws.close(code=4429)
        return
    start = json.loads(await ws.receive_text())
    pid = str(start.get("profile") or "companion").rsplit("/", 1)[-1].removesuffix(".yaml")   # an id, or an old-style path
    path = paths.profiles().get(pid)
    if path is None:
        await ws.close(code=4404)
        return
    missing = registry.missing_settings()
    if missing:
        await ws.send_text(json.dumps({"type": "error", "what": "settings", "missing": missing,
                                       "text": "Missing settings: " + ", ".join(missing)}))
        await ws.close(code=4412)
        return
    profile = Profile.load(path)
    language = start.get("language") or (profile.extra.get("display") or {}).get("language", "en")
    cfg = preset_config(os.getenv("JEV_PRESET", "production"), language=language)
    synth = make_synthesizer(profile, pid)

    async def send(event: dict):
        if event.get("type") in ("line", "listen"):
            LINES[event["id"]] = (event["text"], synth)
            while len(LINES) > MAX_LINES:
                LINES.popitem(last=False)
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    judge = registry.create("judge")
    session = Session(profile, send=send, judge=judge, recognizer=make_recognizer(language),
                      responder=registry.create("llm"), vad=EnergyVAD(), config=cfg,
                      recorder=Recorder(paths.runs_dir() / f"call-{time.strftime('%Y%m%d-%H%M%S')}.jsonl" if RECORD else None))
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
            if DAY_BUDGET_S and spent_today() + time.monotonic() - started > DAY_BUDGET_S:
                await ws.send_text(json.dumps({"type": "hangup", "why": "daily limit"}))
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
        spent_today()
        SPENT["seconds"] += time.monotonic() - started
        try:
            await session.close()
        finally:
            await judge.aclose()


NO_STALE = {"Cache-Control": "no-cache"}     # revalidate the page's files each time, so an update is never half-applied


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers=NO_STALE)


@app.get("/{name:path}")
def web_file(name: str):
    """Everything else the page asks for comes from web/ (scripts, styles, images), never from outside it."""
    path = (WEB / name).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers=NO_STALE)
