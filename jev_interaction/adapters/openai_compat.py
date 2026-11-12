"""Any OpenAI-compatible chat endpoint as the responder (xAI grok, OpenAI, vLLM, Ollama...). Lines are yielded as soon as
a newline arrives, so synthesis of the first line starts while the model is still writing the rest.

Reasoning is switched off by default where the provider has a switch, as the production engine does: a call cannot wait
for a model to think (grok-4.3 with reasoning on took ~8 s to its first word; off, well under a second). LLM_EXTRA_BODY
(a JSON object) is merged into every request to override this or to pass anything else."""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import httpx


def no_reasoning(base_url: str) -> dict:
    """The provider's own switch for "answer at once, no thinking", from the endpoint's host."""
    host = urlparse(base_url).hostname or ""
    if host.endswith("x.ai"):
        return {"reasoning_effort": "none"}
    if host.endswith(("bytepluses.com", "volces.com", "z.ai", "bigmodel.cn")):
        return {"thinking": {"type": "disabled"}}
    if host.endswith("dashscope.aliyuncs.com") or host.endswith("dashscope-intl.aliyuncs.com"):
        return {"enable_thinking": False}
    return {}


class OpenAICompatResponder:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, temperature: float | None = None):
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.key = api_key or os.getenv("LLM_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL", "")
        if not self.base_url or not self.model:
            raise ValueError("set LLM_BASE_URL and LLM_MODEL (any OpenAI-compatible endpoint and one of its models)")
        self.temperature = temperature if temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.extra = {**no_reasoning(self.base_url), **json.loads(os.getenv("LLM_EXTRA_BODY", "") or "{}")}

    async def lines(self, messages, max_tokens=160):
        body = {"model": self.model, "messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": self.temperature}
        buf = ""
        async with httpx.AsyncClient(timeout=30) as http:
            for attempt in (0, 1):
                async with http.stream("POST", f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                       json={**body, **self.extra}) as r:
                    if r.status_code == 400 and self.extra and attempt == 0:
                        # this model has no such switch (grok-4.5+ always reason, non-reasoning models take no
                        # reasoning parameter): drop the extras for the rest of the call and ask again
                        await r.aread()
                        self.extra = {}
                        continue
                    r.raise_for_status()
                    async for raw in r.aiter_lines():
                        if not raw.startswith("data: ") or raw == "data: [DONE]":
                            continue
                        choices = json.loads(raw[6:]).get("choices") or []
                        delta = (choices[0].get("delta") or {}).get("content") or "" if choices else ""
                        buf += delta
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            if line.strip():
                                yield line.strip()
                    break
        if buf.strip():
            yield buf.strip()
