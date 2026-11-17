"""Jev (TypeSafe systemone): a state in plain text, multiple-choice questions, a probability per choice back.

One request can carry several questions about the same state; a typical answer comes back in well under 100 ms.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

JEV_URL = os.getenv("JEV_URL", "https://api.typesafe.ai/v1/systemone")


def public_endpoint(url: str) -> bool:
    """The documented, keyless AmigosJev endpoint; never forward another provider's key to it."""
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.netloc in ("jev.amigos-robot.com", "jev.amigos-robot.com:443")
            and parsed.path.rstrip("/") == "/v1/systemone" and not parsed.query and not parsed.fragment)


class JudgeError(RuntimeError):
    pass


class JevClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, url: str | None = None, timeout: float = 10.0,
                 keepalive_expiry: float = 60.0):
        self.url = url or os.getenv("JEV_URL") or JEV_URL
        self.public = public_endpoint(self.url)
        self.api_key = "" if self.public else (os.getenv("JEV_API_KEY", "") if api_key is None else api_key)
        self.model = model or os.getenv("JEV_MODEL") or ("jev-lite" if self.public else "jev-latest")
        # Retain idle sockets across the caller's next sentence, just as the LLM/TTS pools do.
        # Remote closes still reconnect normally; request content and decision timing are unchanged.
        self._http = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(
            max_connections=100, max_keepalive_connections=20, keepalive_expiry=keepalive_expiry))

    async def ask(self, questions: dict, state: str) -> dict:
        """{name: {"choice": str, "probabilities": {choice: p}}} for every question asked."""
        if not self.api_key and not self.public:
            raise JudgeError("JEV_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = await self._http.post(self.url, headers=headers,
                                  json={"model": self.model, "state": state, "questions": questions})
        if r.status_code != 200:
            raise JudgeError(f"jev {r.status_code}: {r.text[:200]}")
        return r.json()["answers"]

    async def aclose(self):
        await self._http.aclose()


def probs(answers: dict, name: str) -> dict[str, float]:
    return (answers.get(name) or {}).get("probabilities", {}) or {}
