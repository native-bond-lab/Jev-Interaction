"""Opt-in local speech fixture; production files and dialogue scheduling are untouched."""
from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

ROOT = Path(__file__).resolve().parents[1]


def install(app, *, label):
    router = APIRouter()

    @router.get("/__probe")
    async def page():
        html = (ROOT / "jev_interaction/server/web/index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("<head>", '<head><base href="/"><script src="/__probe/driver.js"></script>', 1))

    @router.get("/__probe/driver.js")
    async def driver():
        return FileResponse(ROOT / "tools/voice_browser_fixture.js", media_type="application/javascript")

    @router.get("/__probe/input.wav")
    async def audio():
        return FileResponse(ROOT / ".local/domestic-input.wav", media_type="audio/wav")

    @router.post("/__probe/result")
    async def result(request: Request):
        # This export intentionally excludes transcripts, provider errors, URLs, headers and keys.
        raw = await request.body()
        if len(raw) > 40000:
            raise HTTPException(413)
        body = json.loads(raw)
        number = lambda value: type(value) in (int, float) and math.isfinite(value)
        report = {"stack": label, "ok": body.get("ok") is True,
                  "kind": "prerecorded Chinese speech -> real providers -> original browser player; not physical speaker latency"}
        for key in ("greeting_ms", "frames_sent"):
            if number(body.get(key)):
                report[key] = body[key]
        report["rounds"] = [{k: v for k, v in row.items() if k in (
            "input_duration_ms", "input_end_to_line_ms", "input_end_to_play_ms", "line_to_play_ms") and number(v)}
                            for row in body.get("rounds", [])[:2] if isinstance(row, dict)]
        report["events"] = [{k: v for k, v in row.items() if
                             (k == "at_ms" and number(v)) or
                             (k == "type" and v in ("call_start", "line", "asr_final", "user_closed", "playing", "ended",
                                                     "playback_idle", "input_start", "input_end", "provider_error", "closed"))}
                            for row in body.get("events", [])[:400] if isinstance(row, dict)]
        report["reason"] = body.get("reason") if body.get("reason") in (
            "timeout", "provider_error", "socket_closed", "browser_error") else None
        run = request.query_params.get("run", "0")
        if run not in ("0", "1", "2", "3", "4"):
            raise HTTPException(400)
        report["run"] = int(run)
        target = ROOT / "experiments/latency_20261117/domestic-stack" / f"browser-{label}-{run}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"saved": True}

    app.router.routes[0:0] = router.routes
