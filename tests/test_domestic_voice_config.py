"""Provider-switch contracts: keyless public judge, original authenticated judge, private profile isolation."""
import json

import httpx
import pytest

from jev_interaction.adapters import registry
from jev_interaction.adapters.doubao import auth_headers
from jev_interaction.judge.client import JevClient, JudgeError
from tools.local_voice_profile import RedactingFormatter, activate, read_profile

PUBLIC_URL = "https://jev.amigos-robot.com/v1/systemone"


def test_separate_speech_keys_never_cross_nodes(monkeypatch):
    monkeypatch.setenv("DOUBAO_API_KEY", "shared-private")
    monkeypatch.setenv("DOUBAO_ASR_API_KEY", "asr-private")
    monkeypatch.setenv("DOUBAO_TTS_API_KEY", "tts-private")
    assert auth_headers(asr=True) == {"X-Api-Key": "asr-private"}
    assert auth_headers() == {"X-Api-Key": "tts-private"}
    monkeypatch.delenv("DOUBAO_API_KEY")
    monkeypatch.setenv("DOUBAO_ASR_RESOURCE_ID", "test-asr")
    monkeypatch.setenv("DOUBAO_TTS_RESOURCE_ID", "test-tts")
    monkeypatch.setenv("DOUBAO_TTS_VOICE", "test-voice")
    assert registry.get("asr", "doubao").missing() == []
    assert registry.get("tts", "doubao").missing() == []


async def test_public_judge_uses_documented_body_without_forwarding_old_key(monkeypatch):
    monkeypatch.setenv("JEV_URL", PUBLIC_URL)
    monkeypatch.setenv("JEV_API_KEY", "old-provider-private-key")
    monkeypatch.delenv("JEV_MODEL", raising=False)
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(200, json={"answers": {"done": {"probabilities": {"yes": 1.0}}}})

    client = JevClient()
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    questions = {"done": {"type": "choice", "instructions": "Finished?", "criteria": {"yes": "done", "no": "continues"}}}
    try:
        assert await client.ask(questions, "A test.") == {"done": {"probabilities": {"yes": 1.0}}}
        assert str(seen[0].url) == PUBLIC_URL
        assert "authorization" not in seen[0].headers
        assert json.loads(seen[0].content) == {"model": "jev-lite", "state": "A test.", "questions": questions}
        assert "JEV_API_KEY" not in registry.get("judge").missing()
    finally:
        await client.aclose()


@pytest.mark.parametrize("url", ["https://api.typesafe.ai/v1/systemone", "https://jev.amigos-robot.com.evil/v1/systemone",
                                 "http://jev.amigos-robot.com/v1/systemone", "https://jev.amigos-robot.com/other"])
async def test_other_judge_endpoints_still_require_key(monkeypatch, url):
    monkeypatch.setenv("JEV_URL", url)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    client = JevClient()
    try:
        assert "JEV_API_KEY" in registry.get("judge").missing()
        with pytest.raises(JudgeError, match="JEV_API_KEY"):
            await client.ask({}, "test")
    finally:
        await client.aclose()


def test_private_profile_can_have_blank_key_without_shell_evaluation(tmp_path, monkeypatch):
    path = tmp_path / "test.env"
    path.write_text('JEV_API_KEY=\nLLM_API_KEY="private-value"\nVOICE_TEST_DIRECT=1\n', encoding="utf-8-sig")
    assert read_profile(path)["JEV_API_KEY"] == ""
    for key in ("JEV_API_KEY", "LLM_API_KEY", "VOICE_TEST_DIRECT", "JEV_RUNS_DIR", "NO_PROXY", "no_proxy",
                "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, "before")
    monkeypatch.setattr(RedactingFormatter, "secrets", [])
    values = activate(path)
    assert values["LLM_API_KEY"] == "private-value"
    import os
    assert os.environ["JEV_API_KEY"] == ""
    assert os.environ["NO_PROXY"] == "*"
    assert "HTTPS_PROXY" not in os.environ
