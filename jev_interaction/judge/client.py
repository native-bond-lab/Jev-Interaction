"""Jev (TypeSafe systemone): a state in plain text, multiple-choice questions, a probability per choice back.

One request can carry several questions about the same state; a typical answer comes back in well under 100 ms.
"""
from __future__ import annotations

import os

import httpx

JEV_URL = os.getenv("JEV_URL", "https://api.typesafe.ai/v1/systemone")


class JudgeError(RuntimeError):
    pass


class JevClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, url: str = JEV_URL, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("JEV_API_KEY", "")
        self.model = model or os.getenv("JEV_MODEL", "jev-latest")
        self.url = url
        self._http = httpx.AsyncClient(timeout=timeout)

    async def ask(self, questions: dict, state: str) -> dict:
        """{name: {"choice": str, "probabilities": {choice: p}}} for every question asked."""
        if not self.api_key:
            raise JudgeError("JEV_API_KEY is not set")
        r = await self._http.post(self.url, headers={"Authorization": f"Bearer {self.api_key}"},
                                  json={"model": self.model, "state": state, "questions": questions})
        if r.status_code != 200:
            raise JudgeError(f"jev {r.status_code}: {r.text[:200]}")
        return r.json()["answers"]

    async def aclose(self):
        await self._http.aclose()


def probs(answers: dict, name: str) -> dict[str, float]:
    return (answers.get(name) or {}).get("probabilities", {}) or {}
