"""Jev (TypeSafe systemone): a state in plain text, multiple-choice questions, a probability per choice back.

One request can carry several questions about the same state; a typical answer comes back in well under 100 ms.

Other services speak the same protocol. JEV_URL, JEV_MODEL and JEV_HEADERS (a JSON object of extra request headers)
point the judge at one of them; cookbook/stacks.md lists the ones we measured and what to expect of each.
"""
from __future__ import annotations

import json
import os

import httpx

JEV_URL = os.getenv("JEV_URL") or "https://api.typesafe.ai/v1/systemone"   # an empty JEV_URL= line means the default


class JudgeError(RuntimeError):
    pass


class JevClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, url: str | None = None, timeout: float = 10.0,
                 headers: dict | None = None):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "")
        self.model = model or os.getenv("JEV_MODEL", "jev-latest")
        self.url = url or os.getenv("JEV_URL") or JEV_URL          # read now, so the setup page's value is the one used
        self.headers = dict(headers) if headers is not None else json.loads(os.getenv("JEV_HEADERS", "") or "{}")
        if not isinstance(self.headers, dict):
            raise ValueError('JEV_HEADERS must be a JSON object, e.g. {"x-some-header": "true"}')
        # No system proxy: on a machine with Clash or the like, the judge went through it and never connected, and the
        # call went silent with no other sign. This is a direct HTTPS call to a fixed address.
        self._http = httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def ask(self, questions: dict, state: str | dict) -> dict:
        """{name: {"choice": str, "probabilities": {choice: p}}} for every question asked."""
        if not self.api_key:
            raise JudgeError("JEV_API_KEY is not set")
        r = await self._http.post(self.url, headers={**self.headers, "Authorization": f"Bearer {self.api_key}"},
                                  json={"model": self.model, "state": state, "questions": questions})
        if r.status_code != 200:
            raise JudgeError(f"jev {r.status_code}: {r.text[:200]}")
        return r.json()["answers"]

    async def aclose(self):
        await self._http.aclose()


def probs(answers: dict, name: str) -> dict[str, float]:
    return (answers.get(name) or {}).get("probabilities", {}) or {}
