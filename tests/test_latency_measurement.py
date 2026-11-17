"""Measurement failures, configuration boundaries and resource ownership; no provider requests."""
import json
from types import SimpleNamespace

import pytest

from jev_interaction.server.latency_config import snapshot
from tools import benchmark_voice_stack as benchmark
from tools import compare_voice_latency as comparison
from tools.latency_report import summarize


def test_production_defaults_keep_original_segmentation_and_decisions(monkeypatch):
    import ast
    from pathlib import Path

    from jev_interaction.adapters.openai_compat import OpenAICompatResponder
    from jev_interaction.adapters.speech_chunks import SpeechChunks

    monkeypatch.delenv("LLM_CHUNK_MODE", raising=False)
    llm = OpenAICompatResponder("https://offline.invalid/v1", "test", "test")
    assert llm.chunk_mode == "newline"
    chunks = SpeechChunks()
    assert chunks.feed("First sentence. Second sentence.") == []
    assert chunks.feed("\n") == ["First sentence. Second sentence."]
    root = Path(__file__).resolve().parents[1]
    for name in ("turn", "cut_in", "floor", "quiet"):
        relative = f"jev_interaction/decisions/{name}.py"
        assert (root / relative).read_bytes() == (root / "tests/fixtures/latency_baseline" / relative).read_bytes()
    current = ast.parse((root / "jev_interaction/session.py").read_text(encoding="utf-8"))
    original = ast.parse((root / "tests/fixtures/latency_baseline/jev_interaction/session.py").read_text(encoding="utf-8"))
    def methods(tree):
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Session")
        return {node.name: ast.dump(node) for node in cls.body if isinstance(node, ast.AsyncFunctionDef)}
    current, original = methods(current), methods(original)
    for name in ("start", "tick", "_tick_loop", "_segments_loop", "hand_over", "_stop_line", "safe_word"):
        assert current[name] == original[name], name


def test_configuration_excludes_credentials_and_identifies_effective_warmup(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://user:private-password@api.x.ai/v1/private?key=private-query")
    monkeypatch.setenv("LLM_API_KEY", "private-key")
    monkeypatch.setenv("HTTPS_PROXY", "http://private-proxy:1234")
    monkeypatch.setenv("ASR_PROVIDER", "elevenlabs")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_TTS_REUSE_CONNECTION", "0")
    monkeypatch.setenv("ELEVENLABS_TTS_PREWARM", "1")
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL", "test-tts-model")
    config = snapshot()
    assert config["llm_host"] == "api.x.ai" and config["tts_model"] == "test-tts-model"
    assert config["tts_prewarm"] is False and "private" not in json.dumps(config)


@pytest.mark.parametrize("step", [1, 3, 128])
def test_default_chunks_match_original_newline_parser_even_inside_tags(step):
    from jev_interaction.adapters.speech_chunks import SpeechChunks

    text = '\n [laughs\n softly] Hello. More.\n<emphasis>你好。\n再见。</emphasis>\n tail '
    expected = [line.strip() for line in text.split("\n") if line.strip()]
    chunks, actual = SpeechChunks(), []
    for i in range(0, len(text), step):
        actual.extend(chunks.feed(text[i:i + step]))
    actual.extend(chunks.finish())
    assert actual == expected


def test_report_detects_mixed_configs_and_ignores_unknown_config_fields(tmp_path):
    path = tmp_path / "call.jsonl"
    rows = [
        {"event": "latency_config", "tts": "elevenlabs", "tts_model": "voice-model-a", "api_key": "private-key"},
        {"event": "latency_config", "tts": "elevenlabs", "tts_model": "voice-model-b"},
        {"event": "latency", "stage": "tts_prewarm", "ok": False, "outcome": "cancelled", "elapsed_ms": 50},
        {"event": "latency", "stage": "tts_prewarm", "ok": True, "outcome": "complete", "elapsed_ms": 100},
    ]
    path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    report = summarize([path])
    assert report["mixed_configurations"] and len(report["configurations"]) == 2
    assert "private-key" not in json.dumps(report)
    assert report["counts"]["tts_prewarm_cancelled"] == report["counts"]["tts_prewarm_ok"] == 1


@pytest.mark.parametrize("broken", ["llm", "tts"])
async def test_component_sampling_stops_after_three_provider_failures_and_closes_both(monkeypatch, broken):
    closed = []

    class Adapter:
        async def aclose(self):
            closed.append(self)
            if len(closed) == 1:
                raise RuntimeError("private provider detail")

    llm, tts = Adapter(), Adapter()

    async def sample(*_):
        return {"components": {c: {"ok": c != broken} for c in ("llm", "tts")}, "stages": []}

    monkeypatch.setattr(benchmark.paths, "load_env", lambda: None)
    monkeypatch.setattr(benchmark, "OpenAICompatResponder", lambda: llm)
    monkeypatch.setattr(benchmark, "make_tts", lambda: tts)
    monkeypatch.setattr(benchmark, "sample", sample)
    result = await benchmark.run(SimpleNamespace(trials=10, timeout=1))
    assert len(result["trials"]) == 3 and result["stopped_early"]
    assert result["consecutive_failures"][broken] == 3
    assert closed == [tts, llm] and result["cleanup_errors"] == [{"error_type": "RuntimeError"}]
    assert "private provider detail" not in json.dumps(result)


async def test_partial_audio_then_error_is_not_a_successful_sample():
    class LLM:
        async def lines(self, *_, **__):
            yield "test"

    class TTS:
        async def audio(self, *_):
            yield b"partial audio"
            raise RuntimeError("private body")

    trial = await benchmark.sample(LLM(), TTS(), 1)
    assert trial["components"]["llm"]["ok"] and not trial["components"]["tts"]["ok"]
    summary = benchmark.summarize([trial])
    assert summary["first"]["metrics"]["request_to_first_audio_ms"] == {"n": 0}
    assert "private body" not in json.dumps(trial)


async def test_connection_ab_stops_when_one_mode_continuously_fails(monkeypatch):
    closed = []

    class Client:
        def __init__(self, **_):
            self.reuse_connection = True

        async def aclose(self):
            closed.append(self)

    async def measure(client, _):
        return {"ok": client.reuse_connection, "comparison": {"first_ready_ms": {"first_sentence": 10},
                                                               "same_stream_saved_ms": 0}}

    monkeypatch.setattr(comparison.paths, "load_env", lambda: None)
    monkeypatch.setattr(comparison.openai_compat, "OpenAICompatResponder", Client)
    monkeypatch.setattr(comparison, "measure_llm", measure)
    args = SimpleNamespace(llm=True, tts=False, tts_reuse=False, connection_ab=True, trials=10, seed=1731, timeout=1)
    result = await comparison.run(args)
    assert len(result["trials"]) == 3 and result["stopped_early"] and len(closed) == 2
    assert result["consecutive_failures"] == {"llm_fresh": 3, "llm_reuse": 0}
