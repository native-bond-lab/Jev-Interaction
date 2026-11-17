"""The proxy-tolerant experiment harness runs against mock transports, never real credentials."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
from tools import compare_voice_latency as experiment


def test_shadow_chunkers_share_arrival_times_and_verify_same_spoken_text(monkeypatch):
    clock = iter([100.0, 101.0, 102.0, 103.0])
    monkeypatch.setattr(experiment.time, "perf_counter", lambda: next(clock))
    comparison = experiment.ChunkComparison("first_sentence")
    out = []
    out.extend(comparison.feed("第一句。"))
    out.extend(comparison.feed("后续文字"))
    out.extend(comparison.feed("。"))
    out.extend(comparison.finish())
    result = comparison.result(99.0, True)
    assert out == ["第一句。", "后续文字。"]
    assert result["first_ready_ms"] == {"newline": 4000.0, "first_sentence": 2000.0}
    assert result["same_stream_saved_ms"] == 2000.0 and result["same_spoken_text"]


def test_shadow_early_newline_control_does_not_invent_a_gain(monkeypatch):
    monkeypatch.setattr(experiment.time, "perf_counter", lambda: 100.0)
    comparison = experiment.ChunkComparison("newline")
    assert comparison.feed("你好。\n") == ["你好。"]
    comparison.finish()
    assert comparison.result(99.0, True)["same_stream_saved_ms"] == 0.0


@pytest.mark.parametrize("second_bytes, expected_ms", [(4096, 250.0), (1, 500.0)])
def test_shadow_audio_buffering_on_identical_bytes(monkeypatch, second_bytes, expected_ms):
    clock = iter([10.0, 10.25, 10.5])
    monkeypatch.setattr(experiment.time, "perf_counter", lambda: next(clock))
    comparison = experiment.AudioComparison()
    comparison.feed(b"a" * 128)
    comparison.feed(b"b" * second_bytes)
    comparison.finish()
    result = comparison.result(9.0, True)
    assert result["same_stream_saved_ms"] == expected_ms
    assert result["first_chunk_bytes"] == 128 and result["audio_bytes"] == 128 + second_bytes
    assert result["same_audio_bytes"]


def test_empty_or_failed_samples_do_not_turn_into_zero_latency():
    trials = [{"samples": {"llm": {"ok": False, "error_type": "ConnectTimeout"}}}]
    summary = experiment.summarize(trials)
    assert summary["llm"]["successful"] == 0
    assert summary["llm"]["failed_or_skipped"] == 1
    assert summary["llm"]["same_stream_saved_ms"]["distribution"] == {"n": 0}
    assert experiment.paired_summary([])["median_ci95_ms"] is None
    failed = {"ok": False, "error_type": "ConnectError", "network": {"tcp_connections_started": 1,
              "phases": [{"phase": "proxy.start_tls.failed"}]}}
    paired = [{"samples": {"llm_reuse": failed, "llm_fresh": failed}} for _ in range(2)]
    group = experiment.summarize(paired)["connection_strategy"]["groups"]["llm_fresh"]
    assert group["after_cold_pair_first_ready_ms"] == {"n": 0}
    assert group["tls_failed_calls"] == group["failed"] == 2


def test_connection_summary_separates_first_cold_pair_and_counts_failed_pairs():
    def sample(first):
        return {"ok": True, "comparison": {"first_ready_ms": {"first_sentence": first}, "same_stream_saved_ms": 0}}

    trials = [
        {"samples": {"llm_reuse": sample(1000), "llm_fresh": sample(1)}},
        {"samples": {"llm_reuse": sample(10), "llm_fresh": sample(20)}},
        {"samples": {"llm_reuse": {"ok": False}, "llm_fresh": sample(20)}},
    ]
    summary = experiment.summarize(trials)["connection_strategy"]
    assert summary["failed_pairs_after_warmup"] == 1
    assert summary["groups"]["llm_reuse"]["successful"] == 2
    assert summary["groups"]["llm_reuse"]["failed"] == 1
    assert summary["groups"]["llm_reuse"]["after_cold_pair_first_ready_ms"]["n"] == 1
    assert summary["groups"]["llm_fresh"]["after_cold_pair_first_ready_ms"]["n"] == 2
    assert summary["fresh_minus_reuse_first_sentence_ms"]["distribution"]["p50_ms"] == 10
    assert summary["fresh_minus_reuse_first_sentence_ms"]["median_ci95_ms"] is None
    assert experiment.paired_summary([2.0] * 10)["median_ci95_ms"] == [2.0, 2.0]


async def test_full_randomized_harness_reuses_client_and_never_saves_text_or_keys(monkeypatch):
    client_type, clients, requests = httpx.AsyncClient, [], []

    def handle(request):
        requests.append(request.url.path)
        if request.url.path.endswith("chat/completions"):
            text = 'data: {"choices":[{"delta":{"content":"private generated text. Next"}}]}\n\n'
            text += 'data: {"choices":[{"delta":{"content":" sentence.\\n"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, content=text.encode())
        return httpx.Response(200, content=b"a" * 200 + b"b" * 4096)

    def client(**kwargs):
        made = client_type(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(experiment.paths, "load_env", lambda: None)
    for key, value in {"LLM_BASE_URL": "https://offline.invalid/v1", "LLM_MODEL": "test", "LLM_API_KEY": "private-key",
                       "LLM_EXTRA_BODY": "{}"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(experiment.registry, "create", lambda *_, **__: ElevenLabsTTS("test", "test", "private-tts-key"))
    result = await experiment.run(SimpleNamespace(seed=1731, trials=4, llm=True, tts=True, connection_ab=True, timeout=1))
    assert len(requests) == 12  # eight LLM calls, four TTS calls, none outside MockTransport
    assert len(clients) == 9  # one pooled LLM client, four fresh LLM clients, four TTS clients
    assert all(client.is_closed for client in clients)
    assert result["summary"]["llm"]["successful"] == 8
    assert result["summary"]["tts"]["successful"] == 4
    assert all(trial["samples"]["llm_reuse"]["comparison"]["same_spoken_text"] for trial in result["trials"])
    serialized = json.dumps(result)
    assert "private generated text" not in serialized and "private-key" not in serialized and "private-tts-key" not in serialized
    assert result["trials"][0]["samples"]["llm_reuse"]["network"]["responses"][0]["http_status"] == 200


async def test_failed_real_request_path_is_sanitized_and_counted(monkeypatch):
    from jev_interaction.adapters.openai_compat import OpenAICompatResponder

    llm = OpenAICompatResponder("https://offline.invalid/v1", "private-key", "test")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(401, text="private server body with credentials")))
    try:
        result = await experiment.measure_llm(llm, 1)
    finally:
        await llm.aclose()
    assert not result["ok"] and result["http_status"] == 401
    assert "private" not in json.dumps(result)
    assert result["comparison"]["same_spoken_text"] is None


async def test_tts_warm_probe_borrows_one_pool_and_closes_it_at_the_end(monkeypatch):
    client_type, clients = httpx.AsyncClient, []

    def client(**kwargs):
        made = client_type(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"a" * 6000)), **kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(experiment.paths, "load_env", lambda: None)
    monkeypatch.setattr(experiment.registry, "create", lambda *_, **__: ElevenLabsTTS("test", "test", "private-key"))
    result = await experiment.run(SimpleNamespace(seed=1731, trials=3, llm=False, tts=True, tts_reuse=True,
                                                connection_ab=False, timeout=1))
    assert result["summary"]["tts"]["successful"] == 3
    assert len(clients) == 1 and clients[0].is_closed
    assert all(t["samples"]["tts"]["network"]["responses"][0]["http_status"] == 200 for t in result["trials"])
    assert "private-key" not in json.dumps(result)


async def test_prewarm_harness_separates_setup_and_formal_speech_and_closes_each_arm(monkeypatch):
    from tools import compare_tts_prewarm as prewarm

    client_type, clients, requests = httpx.AsyncClient, [], []

    def handle(request):
        requests.append(request.method)
        return httpx.Response(200, content=b"private metadata" if request.method == "GET" else b"audio" * 1000)

    def client(**kwargs):
        made = client_type(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(prewarm.paths, "load_env", lambda: None)
    monkeypatch.setattr(prewarm, "make_tts", lambda: ElevenLabsTTS("test", "test", "private-key"))
    result = await prewarm.run(SimpleNamespace(seed=1731, trials=3, timeout=1, lead_ms=None))
    assert requests.count("POST") == 6 and requests.count("GET") == 3
    assert len(clients) == 6 and all(c.is_closed for c in clients)
    assert result["summary"]["cold_minus_prewarm_first_audio_ms"]["distribution"]["n"] == 3
    assert result["summary"]["groups"]["prewarm"]["completed_ok_warmups"] == 3
    for trial in result["trials"]:
        assert set(trial["order"]) == {"cold", "prewarm"}
        sample = trial["samples"]["prewarm"]
        assert sample["warmup_completed_at_speech"] and sample["warmup"]["http_status"] == 200
        assert len(sample["warmup_network"]["responses"]) == len(sample["speech"]["network"]["responses"]) == 1
        assert sample["setup_to_first_audio_ms"] >= sample["speech"]["comparison"]["direct_first_audio_ms"]
    assert "private" not in json.dumps(result)


async def test_prewarm_harness_fixed_lead_does_not_wait_for_slow_warmup(monkeypatch):
    from tools import compare_tts_prewarm as prewarm

    started, closed = asyncio.Event(), asyncio.Event()

    class Metadata(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            closed.set()

    def handle(request):
        return httpx.Response(200, stream=Metadata()) if request.method == "GET" else httpx.Response(200, content=b"audio")

    synth = ElevenLabsTTS("local", "local", "local")
    synth._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(prewarm, "make_tts", lambda: synth)
    result = await asyncio.wait_for(prewarm.arm("prewarm", 1, lead_ms=20), 1)
    assert started.is_set() and closed.is_set()
    assert not result["warmup_completed_at_speech"] and result["warmup"]["outcome"] == "cancelled"
    assert result["speech"]["ok"] and synth._http is None


async def test_prewarm_harness_stops_after_three_consecutive_synthesis_failures(monkeypatch):
    from tools import compare_tts_prewarm as prewarm

    client_type, clients, syntheses = httpx.AsyncClient, [], []

    def handle(request):
        if request.method == "POST":
            syntheses.append(True)
        return httpx.Response(200 if request.method == "GET" else 503, content=b"private provider body")

    def client(**kwargs):
        made = client_type(transport=httpx.MockTransport(handle), **kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(prewarm.paths, "load_env", lambda: None)
    monkeypatch.setattr(prewarm, "make_tts", lambda: ElevenLabsTTS("test", "test", "private-key"))
    result = await prewarm.run(SimpleNamespace(seed=1731, trials=10, timeout=1, lead_ms=None))
    assert result["stopped_early"] and len(syntheses) == len(clients) == 3 and all(c.is_closed for c in clients)
    assert len(result["trials"]) == 2 and len(result["trials"][-1]["samples"]) == 1
    assert result["summary"]["cold_minus_prewarm_first_audio_ms"]["distribution"] == {"n": 0}
    assert "private" not in json.dumps(result)
