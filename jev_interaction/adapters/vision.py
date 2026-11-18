"""The agent's eyes on a video call: a picture the page took when the view changed, put into one plain sentence.

Any OpenAI-compatible endpoint with a vision model works. VISION_BASE_URL, VISION_API_KEY and VISION_MODEL pick it; the
first two fall back to the responder's LLM_BASE_URL and LLM_API_KEY. No model is chosen for you: without VISION_MODEL the
call runs without eyes, as before. The sentence goes into the call's record, where Jev and the responder both read it.
"""
from __future__ import annotations

import base64
import os

import httpx

from .openai_compat import no_reasoning

PROMPT = ("You are the eyes of {name}, who is on a video call with the user. This is the picture now. What {name} saw "
          "before: {before}\nIn one short sentence in {language}, say what is new in the picture: what the user did, "
          "picked up, showed or put down, who or what came or went. Plain facts, no guessing at feelings, no description "
          "of the room for its own sake. If nothing worth a word has changed, answer exactly: nothing")


class OpenAISeer:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: float = 8.0):
        self.base_url = (base_url or os.getenv("VISION_BASE_URL") or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.getenv("VISION_API_KEY") or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("VISION_MODEL", "")
        if not self.base_url or not self.model:
            raise ValueError("set VISION_MODEL (and VISION_BASE_URL unless the responder's endpoint serves it)")
        self.extra = no_reasoning(self.base_url)    # a look cannot wait for a model to think, as for the responder
        self._http = httpx.AsyncClient(timeout=float(os.getenv("VISION_TIMEOUT_S", timeout)))

    async def describe(self, image: bytes, media_type: str = "image/jpeg", *, before: str = "", name: str = "the agent",
                       language: str = "English") -> str:
        url = f"data:{media_type};base64,{base64.b64encode(image).decode()}"
        text = PROMPT.format(name=name, before=before or "(nothing yet: this is the first look)", language=language)
        body = {"model": self.model, "max_tokens": 60, "temperature": 0.2, "messages": [
            {"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]}]}
        r = await self._http.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                  json={**body, **self.extra})
        if r.status_code == 400 and self.extra:      # this model has no such switch: ask again without it, and from now on
            self.extra = {}
            r = await self._http.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                      json=body)
        r.raise_for_status()
        said = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        said = said.strip().strip('"')
        return "" if said.lower().rstrip(".") in ("nothing", "") else said
