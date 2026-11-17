"""Boundary, lifecycle and incremental-delivery checks; no keys or provider traffic."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from jev_interaction.adapters.openai_compat import OpenAICompatResponder
from jev_interaction.adapters.speech_chunks import SpeechChunks
from jev_interaction.latency import CallTimings, TimedSynthesizer, latency_scope, observe


@pytest.mark.parametrize("step", [1, 2, 7, 200])
@pytest.mark.parametrize(("text", "expected"), [
    ("你好。后面这句。再一句。\n下一行", ["你好。", "后面这句。再一句。", "下一行"]),
    ('“你好！”然后接着说。', ['“你好！”', '然后接着说。']),
    ("[whispers] Dr. Lee paid 3.14 dollars. Then he left. One more.\nBye.",
     ["[whispers] Dr. Lee paid 3.14 dollars.", "Then he left. One more.", "Bye."]),
    ("[laughs... softly] 好呀！可以。", ["[laughs... softly] 好呀！", "可以。"]),
    ("Try example.com first. Then ask me.", ["Try example.com first.", "Then ask me."]),
    ("Mr. J. Lee lives in the U.S. today. He said yes.", ["Mr. J. Lee lives in the U.S. today.", "He said yes."]),
    ("\n\nHello!\nNext.", ["Hello!", "Next."]),
    ("No punctuation yet", ["No punctuation yet"]),
    ("[laughs]\n你好。后面继续。", ["[laughs]", "你好。", "后面继续。"]),
    ("<emphasis>你好。后面继续。</emphasis>", ["<emphasis>你好。后面继续。</emphasis>"]),
])
def test_first_sentence_boundaries_across_arbitrary_deltas(text, expected, step):
    chunks, out = SpeechChunks("first_sentence"), []
    for start in range(0, len(text), step):
        out.extend(chunks.feed(text[start:start + step]))
    out.extend(chunks.finish())
    assert out == expected


def test_newline_mode_retains_original_segmentation():
    chunks = SpeechChunks("newline")
    assert chunks.feed("你好。再说一句。") == []
    assert chunks.feed("\n下一行") == ["你好。再说一句。"]
    assert chunks.finish() == ["下一行"]
    with pytest.raises(ValueError):
        SpeechChunks("unknown")


def sse(content):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n").encode()


class GatedStream(httpx.AsyncByteStream):
    def __init__(self):
        self.gate, self.closed = asyncio.Event(), False

    async def __aiter__(self):
        yield sse("你好。")
        yield sse("后面还在写")
        await self.gate.wait()
        yield sse("，现在完成。\n")
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("mode", ["first_sentence", "newline"])
async def test_actual_sse_yields_early_only_in_first_sentence_mode(monkeypatch, mode):
    monkeypatch.setenv("LLM_CHUNK_MODE", mode)
    stream = GatedStream()
    llm = OpenAICompatResponder("https://example.invalid/v1", "test", "test-model")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    iterator = llm.lines([])
    first = asyncio.create_task(anext(iterator))
    try:
        if mode == "first_sentence":
            assert await asyncio.wait_for(asyncio.shield(first), 1) == "你好。"
            assert not stream.gate.is_set()  # the rest of the model output has not been released
        else:
            # Advance through a few scheduling turns; there is deliberately no wall-clock latency assumption.
            for _ in range(10):
                await asyncio.sleep(0)
            assert not first.done()
        stream.gate.set()
        initial = await asyncio.wait_for(first, 1)
        rest = [text async for text in iterator]
        assert initial + "".join(rest) == "你好。后面还在写，现在完成。"
    finally:
        stream.gate.set()
        if not first.done():
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        await iterator.aclose()
        await llm.aclose()
    assert stream.closed


@pytest.mark.parametrize("reuse, expected_clients", [("1", 1), ("0", 2)])
async def test_http_client_reuse_switch_and_close(monkeypatch, reuse, expected_clients):
    monkeypatch.setenv("LLM_REUSE_CONNECTION", reuse)
    clients, real_client = [], httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda _: httpx.Response(200, content=sse("Hello.")))
        made = real_client(**kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    llm = OpenAICompatResponder("https://example.invalid/v1", "test", "test-model")
    for _ in range(2):
        assert [text async for text in llm.lines([])] == ["Hello."]
    assert len(clients) == expected_clients
    assert all(c.is_closed for c in clients) if reuse == "0" else not clients[0].is_closed
    await llm.aclose()
    assert all(c.is_closed for c in clients)


async def test_done_event_flushes_without_waiting_for_http_close(monkeypatch):
    class StaysOpen(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse("Hello")
            yield b"data:[DONE]\n\n"
            await asyncio.Event().wait()

    llm = OpenAICompatResponder("https://example.invalid/v1", "test", "test-model")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=StaysOpen())))

    async def consume():
        return [text async for text in llm.lines([])]

    try:
        assert await asyncio.wait_for(consume(), 1) == ["Hello"]
    finally:
        await llm.aclose()


async def test_unsupported_extras_retry_and_timing_are_per_request(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"unsupported": true}')
    bodies, rec = [], MemoryRecorder()

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(400) if len(bodies) == 1 else httpx.Response(200, content=sse("Hello."))

    llm = OpenAICompatResponder("https://example.invalid/v1", "test", "test-model")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        with latency_scope(rec, gen=1):
            assert [text async for text in llm.lines([])] == ["Hello."]
        observe("outside")  # context must have been reset
        assert "unsupported" in bodies[0] and "unsupported" not in bodies[1]
        stages = [row["stage"] for row in rec.rows]
        assert stages.count("llm_request") == 2
        assert stages.count("llm_first_token") == stages.count("llm_first_chunk") == 1
        assert rec.rows[-1]["status"] == "complete" and "outside" not in stages
        assert all(row["gen"] == 1 for row in rec.rows)
    finally:
        await llm.aclose()


class MemoryRecorder:
    def __init__(self):
        self.rows = []

    def write(self, event, **fields):
        self.rows.append({"event": event, **fields})

    def close(self):
        pass


def test_timings_correlate_ids_bound_memory_and_ignore_invalid_metadata(monkeypatch):
    import jev_interaction.latency as latency
    clock, rec = [1.0], MemoryRecorder()
    monkeypatch.setattr(latency, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    timing = CallTimings(rec)
    timing.voice(1.0)
    clock[0] = 1.4
    timing.asr_final(1)
    clock[0] = 1.7
    timing.reply(1, "spoke", answers_user=True)
    clock[0] = 2.2
    timing.line(1, "a")
    clock[0] = 2.5
    timing.playback({"gen": 1, "id": "a", "client_receive_to_play_ms": 200})
    row = rec.rows[-1]
    assert row["voice_to_playback_ack_ms"] == 1500
    assert row["asr_to_playback_ack_ms"] == 1100
    assert row["response_to_playback_ack_ms"] == 800
    assert row["line_to_playback_ack_ms"] == 300
    assert row["client_receive_to_play_ms"] == 200
    n = len(rec.rows)
    for msg in ({"gen": 1, "id": "a"}, {"gen": 0, "id": "a"}, {"id": []}, {}):
        timing.playback(msg)
    assert len(rec.rows) == n
    for gen in range(2, 302):
        timing.open_utterance()
        timing.reply(gen, "pickup", answers_user=False)
        timing.line(gen, str(gen))
        timing.playback({"gen": gen, "id": str(gen), "client_receive_to_play_ms": float("nan")})
    assert len(timing.replies) <= 64 and len(timing.lines) <= 256
    assert "voice_to_playback_ack_ms" not in rec.rows[-1] and "client_receive_to_play_ms" not in rec.rows[-1]


async def test_tts_observer_preserves_first_chunk_streaming_and_records_cancel():
    class Synth:
        media_type = "audio/mpeg"
        closed = False

        async def audio(self, _):
            try:
                yield b"first"
                await asyncio.Event().wait()
            finally:
                self.closed = True

    rec = MemoryRecorder()
    synth = TimedSynthesizer(Synth(), rec, "a", 1)
    audio = synth.audio("test")
    assert await asyncio.wait_for(anext(audio), 1) == b"first"
    assert rec.rows[-1]["stage"] == "tts_first_audio"
    await audio.aclose()
    assert rec.rows[-1]["stage"] == "tts_end" and not rec.rows[-1]["complete"]
    assert synth.synth.closed


async def test_session_adds_observations_without_changing_events_or_leaking_text():
    from jev_interaction import Profile, Session
    from jev_interaction.adapters.base import Segment
    from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeResponder, FakeVAD

    class ClosingResponder(FakeResponder):
        closed = False

        async def aclose(self):
            self.closed = True

    events, rec, llm = [], MemoryRecorder(), ClosingResponder()

    async def send(event):
        events.append(event)

    session = Session(Profile("Test"), send=send, recorder=rec, judge=FakeJudge(), recognizer=FakeRecognizer(),
                      responder=llm, vad=FakeVAD(), speech="plain")
    session.vad.voice = True
    await session.on_audio(b"\0" * 6400)
    await session.on_segment(Segment("private user text"))
    await session.respond("spoke")
    first = next(e for e in events if e["type"] == "line")
    await session.on_client({"type": "playback", "state": "playing", "id": first["id"], "gen": first["gen"],
                             "client_receive_to_play_ms": 123})
    metrics = [row for row in rec.rows if row["event"] == "latency"]
    assert {"asr_final", "line_sent", "playback_start"} <= {row["stage"] for row in metrics}
    assert "private user text" not in json.dumps(metrics)
    assert metrics[-1]["client_receive_to_play_ms"] == 123
    await session.close()
    assert llm.closed


async def test_stream_cancellation_closes_response_and_keeps_the_pool_usable():
    stream, rec = GatedStream(), MemoryRecorder()
    llm = OpenAICompatResponder("https://example.invalid/v1", "test", "test-model")
    llm.chunk_mode = "first_sentence"  # exercise cancellation with a deliberately gated first-sentence stream
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    iterator = llm.lines([])
    try:
        with latency_scope(rec, gen=2):
            assert await anext(iterator) == "你好。"
            next_chunk = asyncio.create_task(anext(iterator))
            await asyncio.sleep(0)
            next_chunk.cancel()
            with pytest.raises(asyncio.CancelledError):
                await next_chunk
        assert stream.closed and not llm._http.is_closed
        assert rec.rows[-1]["stage"] == "llm_end" and rec.rows[-1]["status"] == "interrupted"
    finally:
        await iterator.aclose()
        await llm.aclose()


def test_report_percentiles_missing_stages_and_failure_counts(tmp_path):
    from tools.latency_report import distribution, summarize

    assert distribution(list(range(1, 21)))["p95_ms"] == 19
    path = tmp_path / "call.jsonl"
    rows = [
        {"event": "respond", "t": 10, "gen": 1, "kind": "spoke"},
        {"event": "send", "type": "line", "t": 11, "gen": 1, "text": "private text"},
        {"event": "send", "type": "line", "t": 12, "gen": 1},
        {"event": "respond", "t": 20, "gen": 2, "kind": "spoke"},
        {"event": "no_reply"},
        {"event": "latency", "stage": "playback_start", "first": True, "response_to_playback_ack_ms": 1400},
        {"event": "latency", "stage": "playback_start", "first": False, "response_to_playback_ack_ms": 2000},
        {"event": "latency", "stage": "llm_end", "status": "interrupted"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\nbroken\n", encoding="utf-8")
    report = summarize([path])
    assert report["metrics"]["respond_to_first_line_ms"]["p50_ms"] == 1000
    assert report["metrics"]["response_to_playback_ack_ms"]["n"] == 1
    assert "request_to_first_audio_ms" not in report["metrics"]
    assert report["counts"]["responses_without_line"] == report["counts"]["no_reply"] == 1
    assert report["counts"]["llm_interrupted"] == report["counts"]["malformed_rows"] == 1
    assert "private text" not in json.dumps(report)


def test_websocket_tts_and_playback_metadata_are_correlated(monkeypatch):
    import threading
    from collections import OrderedDict

    from fastapi.testclient import TestClient

    from jev_interaction.server import app as server
    from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeResponder, FakeSynthesizer, FakeVAD

    played = threading.Event()

    class Recorder(MemoryRecorder):
        def write(self, event, **fields):
            super().write(event, **fields)
            if fields.get("stage") == "playback_start":
                played.set()

    rec = Recorder()
    factories = {"judge": FakeJudge, "asr": FakeRecognizer, "llm": FakeResponder, "tts": FakeSynthesizer}
    monkeypatch.setattr(server.registry, "create", lambda kind, **_: factories[kind]())
    monkeypatch.setattr(server.registry, "missing_settings", lambda: [])
    monkeypatch.setattr(server, "Recorder", lambda _: rec)
    monkeypatch.setattr(server, "best_vad", FakeVAD)
    for name, value in {"MAX_CALLS": 0, "MAX_CALL_S": 0, "DAY_BUDGET_S": 0, "RECORD": False,
                        "EMBEDDER": None, "LINES": OrderedDict()}.items():
        monkeypatch.setattr(server, name, value)
    with TestClient(server.app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "start", "profile": "companion", "language": "en"})
        first = socket.receive_json()
        assert first["type"] == "line"
        assert client.get(first["audio"]).content == first["text"].encode()
        socket.send_json({"type": "playback", "state": "playing", "id": first["id"], "gen": first["gen"],
                          "client_receive_to_play_ms": 75})
        assert played.wait(timeout=2)
    stages = {row["stage"] for row in rec.rows if row["event"] == "latency"}
    assert {"line_sent", "tts_request", "tts_first_audio", "tts_end", "playback_start"} <= stages
    audio = next(row for row in rec.rows if row.get("stage") == "tts_first_audio")
    request = next(row for row in rec.rows if row.get("stage") == "tts_request")
    playback = next(row for row in rec.rows if row.get("stage") == "playback_start")
    assert audio["id"] == playback["id"] == first["id"] and audio["gen"] == playback["gen"] == first["gen"]
    assert request["line_to_tts_request_ms"] >= 0
    assert audio["line_to_first_audio_ms"] >= request["line_to_tts_request_ms"]


async def test_settings_test_closes_the_early_reply_stream_and_client(monkeypatch):
    from jev_interaction.server import settings

    class Client:
        stream_closed = client_closed = False

        async def lines(self, messages, max_tokens):
            try:
                yield "Hi."
                raise AssertionError("only the first line is needed")
            finally:
                self.stream_closed = True

        async def aclose(self):
            assert self.stream_closed
            self.client_closed = True

    client = Client()
    monkeypatch.setattr(settings.R, "create", lambda _: client)
    result = await settings.test("llm", None, None)
    assert result["ok"] and client.client_closed


async def test_session_still_releases_llm_when_recognizer_close_fails():
    from jev_interaction.testing import scripted_session

    class Client:
        closed = False

        async def aclose(self):
            self.closed = True

    async def broken_close():
        raise RuntimeError("ASR close failed")

    session, _, _ = scripted_session()
    session.asr.close = broken_close
    session.llm = Client()
    with pytest.raises(RuntimeError, match="ASR close failed"):
        await session.close()
    assert session.llm.closed


async def test_stream_closing_remains_optional_for_custom_iterators():
    from jev_interaction.adapters.base import closing_stream

    class OneLine:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return "hello"

    async with closing_stream(OneLine()) as stream:
        assert await anext(stream) == "hello"
