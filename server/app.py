"""A runnable call server: one WebSocket per call, one HTTP route for line audio.

    pip install -e ".[server]"; cp .env.example .env  # fill in the keys
    uvicorn server.app:app --port 8080     then open http://localhost:8080

WebSocket /ws: first message {"type": "start", "profile": "examples/profiles/companion.yaml", "language": "en"}, then binary
200 ms PCM16 16 kHz frames and JSON client messages; events come back as JSON.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from jev_interaction import Config, Profile
from jev_interaction.adapters import EnergyVAD
from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
from jev_interaction.adapters.openai_compat import OpenAICompatResponder
from jev_interaction.adapters.scribe import ScribeRealtime
from jev_interaction.judge import JevClient
from jev_interaction.recorder import Recorder
from jev_interaction.session import Session

ROOT = pathlib.Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

app = FastAPI()
LINES: dict[str, str] = {}
TTS = ElevenLabsTTS()


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/client.js")
def client():
    return FileResponse(ROOT / "web" / "client.js", media_type="text/javascript")


@app.get("/tts/{line_id}")
async def tts(line_id: str):
    text = LINES.get(line_id)
    if text is None:
        raise HTTPException(404)
    return StreamingResponse(TTS.audio(text), media_type=TTS.media_type)


@app.websocket("/ws")
async def call(ws: WebSocket):
    await ws.accept()
    start = json.loads(await ws.receive_text())
    profile = Profile.load(ROOT / start.get("profile", "examples/profiles/companion.yaml"))
    cfg = Config(language=start.get("language", "en"))

    async def send(event: dict):
        if event.get("type") in ("line", "listen"):
            LINES[event["id"]] = event["text"]
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    session = Session(profile, send=send, judge=JevClient(), recognizer=ScribeRealtime(language=cfg.language),
                      responder=OpenAICompatResponder(), vad=EnergyVAD(), config=cfg,
                      recorder=Recorder(ROOT / "runs" / f"call-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    await session.start()
    try:
        while True:
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
        await session.close()
