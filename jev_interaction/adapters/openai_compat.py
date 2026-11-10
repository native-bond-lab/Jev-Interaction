"""Any OpenAI-compatible chat endpoint as the responder (xAI grok, OpenAI, vLLM, Ollama...). Lines are yielded as soon as
a newline arrives, so synthesis of the first line starts while the model is still writing the rest."""
from __future__ import annotations

import json
import os

import httpx


class OpenAICompatResponder:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, temperature: float = 0.8):
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.x.ai/v1")).rstrip("/")
        self.key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "grok-4.3")
        self.temperature = temperature

    async def lines(self, messages, max_tokens=160):
        buf = ""
        async with httpx.AsyncClient(timeout=30) as http:
            async with http.stream("POST", f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                   json={"model": self.model, "messages": messages, "stream": True, "max_tokens": max_tokens,
                                         "temperature": self.temperature}) as r:
                async for raw in r.aiter_lines():
                    if not raw.startswith("data: ") or raw == "data: [DONE]":
                        continue
                    delta = json.loads(raw[6:])["choices"][0].get("delta", {}).get("content") or ""
                    buf += delta
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        if line.strip():
                            yield line.strip()
        if buf.strip():
            yield buf.strip()
