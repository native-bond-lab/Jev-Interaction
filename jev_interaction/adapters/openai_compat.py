"""Any OpenAI-compatible chat endpoint as the responder (xAI grok, OpenAI, vLLM, Ollama...). Keep the original newline
boundaries. One HTTP client per responder reuses connections (LLM_REUSE_CONNECTION=0 disables it).
LLM_CHUNK_MODE=first_sentence is a separate opt-in experiment, never the default.

Reasoning is switched off by default where the provider has a switch, as our product's engine does: a call cannot wait
for a model to think (grok-4.3 with reasoning on took ~8 s to its first word; off, well under a second). LLM_EXTRA_BODY
(a JSON object) is merged into every request to override this or to pass anything else."""
from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import urlparse

import httpx

from ..latency import ms, observe
from .speech_chunks import SpeechChunks


async def _drain_sse(lines):
    """Reach HTTP EOF so HTTP/1.1 can reuse the socket; ignore bounded post-DONE trailers."""
    for _ in range(32):
        try:
            await anext(lines)
        except StopAsyncIteration:
            return True
    return False


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
        self.chunk_mode = os.getenv("LLM_CHUNK_MODE", "newline")
        SpeechChunks(self.chunk_mode)  # fail on an invalid setting before sending a billed request
        self.reuse_connection = os.getenv("LLM_REUSE_CONNECTION", "1") != "0"
        self._http: httpx.AsyncClient | None = None

    async def aclose(self):
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def lines(self, messages, max_tokens=160):
        body = {"model": self.model, "messages": messages, "stream": True, "max_tokens": max_tokens, "temperature": self.temperature}
        chunks = SpeechChunks(self.chunk_mode)
        if self._http is None:
            http = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=8, max_keepalive_connections=4,
                                                                    keepalive_expiry=60))
            if self.reuse_connection:
                self._http = http
        else:
            http = self._http
        started, first_token, first_chunk, status = time.monotonic(), None, True, "interrupted"
        try:
            for attempt in (0, 1):
                request_at = time.monotonic()
                observe("llm_request", attempt=attempt + 1, chunk_mode=self.chunk_mode, reuse_connection=self.reuse_connection)
                async with http.stream("POST", f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                                       json={**body, **self.extra}) as r:
                    if r.status_code == 400 and self.extra and attempt == 0:
                        # this model has no such switch (grok-4.5+ always reason, non-reasoning models take no
                        # reasoning parameter): drop the extras for the rest of the call and ask again
                        await r.aread()
                        self.extra = {}
                        continue
                    r.raise_for_status()
                    lines, done = r.aiter_lines(), False
                    async for raw in lines:
                        if not raw.startswith("data:"):
                            continue
                        data = raw[5:].strip()
                        if data == "[DONE]":
                            done = True
                            break
                        if not data:
                            continue
                        choices = json.loads(data).get("choices") or []
                        delta = (choices[0].get("delta") or {}).get("content") or "" if choices else ""
                        if delta and first_token is None:
                            first_token = time.monotonic()
                            observe("llm_first_token", attempt=attempt + 1, request_to_first_token_ms=ms(request_at, first_token))
                        for line in chunks.feed(delta):
                            if first_chunk:
                                observe("llm_first_chunk", request_to_first_chunk_ms=ms(request_at),
                                        first_token_to_first_chunk_ms=ms(first_token))
                                first_chunk = False
                            yield line
                    # Deliver the final text at semantic completion, before waiting for HTTP EOF.
                    for line in chunks.finish():
                        if first_chunk:
                            observe("llm_first_chunk", request_to_first_chunk_ms=ms(request_at),
                                    first_token_to_first_chunk_ms=ms(first_token))
                            first_chunk = False
                        yield line
                    if done and self.reuse_connection:
                        drain_at = time.monotonic()
                        try:
                            # Continue the SAME iterator: aread() after partial streaming raises StreamConsumed.
                            drained = await asyncio.wait_for(_drain_sse(lines), timeout=0.25)
                            outcome = "eof" if drained else "limit"
                        except asyncio.TimeoutError:
                            outcome = "timeout"
                        except httpx.HTTPError:
                            # The model already finished; discard the damaged connection, never retry spoken text.
                            outcome = "transport_error"
                        observe("llm_transport_end", outcome=outcome, duration_ms=ms(drain_at))
                    break
            status = "complete"
        except Exception:
            status = "error"
            raise
        finally:
            observe("llm_end", status=status, duration_ms=ms(started))
            if not self.reuse_connection:
                await http.aclose()
