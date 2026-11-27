"""Doubao Voice shared authentication; the speech API key is separate from a ModelArk LLM key.

Both the new console's API key and the old console's app ID/access token are supported. Fixed official origins
keep credentials off arbitrary URLs. Environment proxy behavior remains unchanged.
"""
from __future__ import annotations

import os


def auth_headers(*, asr=False):
    key = os.getenv("DOUBAO_ASR_API_KEY" if asr else "DOUBAO_TTS_API_KEY") or os.getenv("DOUBAO_API_KEY", "")
    if key:
        return {"X-Api-Key": key}
    app, token = os.getenv("DOUBAO_APP_ID", ""), os.getenv("DOUBAO_ACCESS_TOKEN", "")
    if not app or not token:
        raise ValueError("set DOUBAO_API_KEY, or both DOUBAO_APP_ID and DOUBAO_ACCESS_TOKEN")
    return {"X-Api-App-Key" if asr else "X-Api-App-Id": app, "X-Api-Access-Key": token}
