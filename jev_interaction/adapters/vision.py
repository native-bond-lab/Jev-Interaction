"""The agent's eyes on a video call: a picture the page took when the view changed, put into one plain sentence.

The seer is shown the picture it looked at last beside the new one, so what was there already (the headphones the user
has had on all along) is never news; the first look describes the scene, which is kept as the background.

Any OpenAI-compatible endpoint with a vision model works. VISION_BASE_URL, VISION_API_KEY and VISION_MODEL pick it; the
first two fall back to the responder's LLM_BASE_URL and LLM_API_KEY. No model is chosen for you: without VISION_MODEL the
call runs without eyes, as before. The sentence goes into the call's record, where Jev and the responder both read it.
"""
from __future__ import annotations

import base64
import os

import httpx

from .openai_compat import less_reasoning, no_reasoning

FIRST = ("You are the eyes of {name}, who has just started a video call with the user. In one short sentence in "
         "{language}, say who is in the picture and what they have with them or are doing. Plain facts, no guessing at "
         "feelings.")
CHANGED = ("You are the eyes of {name}, who is on a video call with the user. The first picture is what {name} saw last "
           "({before}); the second is now. In one short sentence in {language}, say what is different in the second: "
           "what the user did, picked up, showed or put down, who or what came or went. Anything that is in both "
           "pictures is not new, however it was described before, and so is the same thing a little moved, turned or lit "
           "differently. Say it as what happened on the call (\"the user has picked up a red mug\"), never about "
           "pictures. Plain facts, no guessing at feelings. If nothing a person on the call would notice has "
           "changed, answer exactly: nothing")
MOVING = (" The second picture is one still from a movement the user has kept up for {s:.0f} s (the camera saw them moving "
          "all that time): say what they are doing, such as waving at the camera or walking about.")


class OpenAISeer:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: float = 8.0):
        self.base_url = (base_url or os.getenv("VISION_BASE_URL") or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.getenv("VISION_API_KEY") or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("VISION_MODEL", "")
        if not self.base_url or not self.model:
            raise ValueError("set VISION_MODEL (and VISION_BASE_URL unless the responder's endpoint serves it)")
        self.extra = no_reasoning(self.base_url)    # a look cannot wait for a model to think, as for the responder
        self._http = httpx.AsyncClient(timeout=float(os.getenv("VISION_TIMEOUT_S", timeout)))

    async def describe(self, image: bytes, media_type: str = "image/jpeg", *, before: str = "", before_image: bytes | None = None,
                       moving_s: float = 0.0, name: str = "the agent", language: str = "English") -> str:
        def part(img: bytes) -> dict:
            return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(img).decode()}"}}
        if before_image is None:
            content = [{"type": "text", "text": FIRST.format(name=name, language=language)}, part(image)]
        else:
            text = CHANGED.format(name=name, before=before or "the scene", language=language)
            text += MOVING.format(s=moving_s) if moving_s else ""
            content = [{"type": "text", "text": text}, part(before_image), part(image)]
        body = {"model": self.model, "max_tokens": 60, "temperature": 0.2, "messages": [{"role": "user", "content": content}]}
        r = await self._http.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                  json={**body, **self.extra})
        while r.status_code == 400 and self.extra:   # the model refuses the switch: one step down, from now on
            self.extra = less_reasoning(self.extra)
            r = await self._http.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                      json={**body, **self.extra})
        r.raise_for_status()
        said = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        said = said.strip().strip('"')
        return "" if said.lower().rstrip(".") in ("nothing", "") else said
