"""Real HTTP/1.1 reuse and safe handling of an SSE provider that stays open after DONE."""
import asyncio
import json

import httpx
import pytest

from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
from jev_interaction.adapters.openai_compat import OpenAICompatResponder
from jev_interaction.latency import latency_scope


def sse(text):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\ndata: [DONE]\n\n").encode()


@pytest.fixture
async def keepalive_endpoint():
    state = {"accepted": 0, "requests": [], "methods": []}
    release_eof, writers, handlers = asyncio.Event(), set(), set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        writers.add(writer)
        state["accepted"] += 1
        connection = state["accepted"]
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                headers = dict(line.split(b":", 1) for line in head.split(b"\r\n")[1:] if b":" in line)
                await reader.readexactly(int(headers.get(b"Content-Length", b"0")))
                state["requests"].append(connection)
                state["methods"].append(head.split(b" ", 1)[0].decode())
                payload = sse("Hello")
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                             b"Transfer-Encoding: chunked\r\nConnection: keep-alive\r\n\r\n")
                writer.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
                await writer.drain()
                # Model completion precedes the transport's final chunk, as in a real SSE stream.
                await release_eof.wait()
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            writers.discard(writer)
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1", state, release_eof
    finally:
        release_eof.set()
        server.close()
        await server.wait_closed()
        for writer in list(writers):
            writer.close()
        if handlers:
            await asyncio.gather(*list(handlers), return_exceptions=True)


@pytest.mark.parametrize("reuse, connections", [(True, 1), (False, 2)])
async def test_real_socket_reuse_after_done_without_delaying_final_text(monkeypatch, keepalive_endpoint, reuse, connections):
    endpoint, state, release_eof = keepalive_endpoint
    client_type = httpx.AsyncClient
    # A local integration test must never use the machine's real proxy.
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(trust_env=False, **kwargs))
    llm = OpenAICompatResponder(endpoint, "local-test", "local-test")
    llm.reuse_connection = reuse
    iterator = llm.lines([])
    try:
        # The HTTP terminator is deliberately withheld. Final speech must already be available.
        assert await asyncio.wait_for(anext(iterator), 1) == "Hello"
        assert not release_eof.is_set()
        release_eof.set()
        assert [line async for line in iterator] == []
        assert [line async for line in llm.lines([])] == ["Hello"]
        assert state["accepted"] == connections
        assert state["requests"] == ([1, 1] if reuse else [1, 2])
    finally:
        release_eof.set()
        await iterator.aclose()
        await llm.aclose()


class Recorder:
    def __init__(self):
        self.rows = []

    def write(self, event, **fields):
        self.rows.append({"event": event, **fields})


@pytest.mark.parametrize("tail, outcome", [("hang", "timeout"), ("error", "transport_error"), ("flood", "limit")])
async def test_post_done_transport_cannot_hang_or_repeat_completed_text(tail, outcome):
    class TrailingStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield sse("Hello")
            if tail == "hang":
                await asyncio.Event().wait()
            elif tail == "error":
                raise httpx.RemoteProtocolError("test-only broken trailer")
            else:
                while True:
                    yield b"data: invalid-post-DONE-data\n\n"

        async def aclose(self):
            self.closed = True

    stream, rec = TrailingStream(), Recorder()
    llm = OpenAICompatResponder("http://offline.invalid/v1", "test", "test")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)))
    try:
        with latency_scope(rec):
            async def consume():
                return [line async for line in llm.lines([])]

            assert await asyncio.wait_for(consume(), 1) == ["Hello"]
        assert stream.closed
        assert next(row for row in rec.rows if row.get("stage") == "llm_transport_end")["outcome"] == outcome
        assert rec.rows[-1]["status"] == "complete"
    finally:
        await llm.aclose()


async def test_cancelling_tail_drain_still_closes_stream():
    draining, closed = asyncio.Event(), asyncio.Event()

    class TrailingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse("Hello")
            draining.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    llm = OpenAICompatResponder("http://offline.invalid/v1", "test", "test")
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=TrailingStream())))

    async def consume():
        return [line async for line in llm.lines([])]

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(draining.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await llm.aclose()


@pytest.mark.parametrize("reuse, expected", [(True, 1), (False, 2)])
async def test_tts_reuses_real_tcp_and_closes_pool(monkeypatch, keepalive_endpoint, reuse, expected):
    endpoint, state, release_eof = keepalive_endpoint
    release_eof.set()
    client_type, clients = httpx.AsyncClient, []

    async def redirect(request):
        request.url = httpx.URL(endpoint)

    def client(**kwargs):
        made = client_type(trust_env=False, event_hooks={"request": [redirect]}, **kwargs)
        clients.append(made)
        return made

    monkeypatch.setattr(httpx, "AsyncClient", client)
    synth = ElevenLabsTTS("local", "local", "local")
    synth.reuse_connection = reuse
    try:
        for _ in range(2):
            assert b"".join([chunk async for chunk in synth.audio("hello")]) == sse("Hello")
        assert state["accepted"] == expected
        assert all(c.is_closed for c in clients) if not reuse else not clients[0].is_closed
    finally:
        await synth.aclose()
    assert all(c.is_closed for c in clients)


async def test_tts_cancelled_response_drops_socket_but_preserves_client(monkeypatch, keepalive_endpoint):
    endpoint, state, release_eof = keepalive_endpoint
    client_type = httpx.AsyncClient

    async def redirect(request):
        request.url = httpx.URL(endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(
        trust_env=False, event_hooks={"request": [redirect]}, **kwargs))
    synth = ElevenLabsTTS("local", "local", "local")
    synth.reuse_connection = True
    iterator = synth.audio("hello")
    try:
        assert await asyncio.wait_for(anext(iterator), 1) == sse("Hello")
        await iterator.aclose()
        assert not synth._http.is_closed
        release_eof.set()
        assert b"".join([chunk async for chunk in synth.audio("hello again")]) == sse("Hello")
        assert state["accepted"] == 2
    finally:
        release_eof.set()
        await iterator.aclose()
        await synth.aclose()


async def test_completed_tts_prewarm_reuses_real_socket_for_first_speech(monkeypatch, keepalive_endpoint):
    endpoint, state, release_eof = keepalive_endpoint
    release_eof.set()
    client_type, requests = httpx.AsyncClient, []

    async def redirect(request):
        requests.append((request.method, str(request.url), dict(request.headers)))
        request.url = httpx.URL(endpoint)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(
        trust_env=False, event_hooks={"request": [redirect]}, **kwargs))
    synth, rec = ElevenLabsTTS("local", "local", "private-key"), Recorder()
    synth.prewarm = synth.reuse_connection = True
    try:
        with latency_scope(rec):
            warm = synth.start_warmup()
            assert synth.start_warmup() is warm
            result = await asyncio.wait_for(warm, 1)
        assert result["ok"] and result["http_status"] == 200
        assert state["methods"] == ["GET"]
        assert requests[0][1] == "https://api.elevenlabs.io/v1/models"
        assert requests[0][2]["xi-api-key"] == "private-key"
        assert b"".join([part async for part in synth.audio("private speech")]) == sse("Hello")
        assert state["requests"] == [1, 1] and state["methods"] == ["GET", "POST"]
        assert requests[1][2]["xi-api-key"] == "private-key"
        assert rec.rows[0]["stage"] == "tts_prewarm" and rec.rows[0]["elapsed_ms"] >= 0
        assert "private" not in json.dumps(rec.rows)
    finally:
        await synth.aclose()


async def test_first_speech_cancels_incomplete_warmup_without_waiting_for_metadata_eof(monkeypatch, keepalive_endpoint):
    endpoint, state, _ = keepalive_endpoint
    client_type, metadata_arrived = httpx.AsyncClient, asyncio.Event()

    async def redirect(request):
        request.url = httpx.URL(endpoint)

    async def headers(response):
        if response.request.method == "GET":
            metadata_arrived.set()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(trust_env=False,
        event_hooks={"request": [redirect], "response": [headers]}, **kwargs))
    synth, rec = ElevenLabsTTS("local", "local", "local"), Recorder()
    synth.prewarm = synth.reuse_connection = True
    iterator = synth.audio("hello")
    try:
        with latency_scope(rec):
            warm = synth.start_warmup()
            await asyncio.wait_for(metadata_arrived.wait(), 1)
            assert await asyncio.wait_for(anext(iterator), 1) == sse("Hello")
        assert warm.cancelled()
        assert state["accepted"] == 2 and state["methods"] == ["GET", "POST"]
        assert rec.rows[0]["outcome"] == "cancelled"
    finally:
        await iterator.aclose()
        await synth.aclose()


@pytest.mark.parametrize("case", ["timeout", "status", "oversize"])
async def test_failed_or_large_prewarm_is_bounded_and_does_not_block_speech(case):
    requests = []

    def handle(request):
        requests.append(request.method)
        if request.method == "GET":
            if case == "timeout":
                raise httpx.ReadTimeout("private provider diagnostic")
            return httpx.Response(401 if case == "status" else 200,
                                  content=b"denied" if case == "status" else b"x" * (256 * 1024 + 1))
        return httpx.Response(200, content=b"audio")

    synth = ElevenLabsTTS("local", "local", "private-key")
    synth.prewarm = synth.reuse_connection = True
    synth._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        result = await synth.start_warmup()
        assert not result["ok"] and "private" not in json.dumps(result)
        assert b"".join([part async for part in synth.audio("hello")]) == b"audio"
        assert requests == ["GET", "POST"]
    finally:
        await synth.aclose()


@pytest.mark.parametrize("prewarm,reuse", [(False, True), (True, False), (False, False)])
async def test_disabled_tts_prewarm_does_not_create_a_client(prewarm, reuse):
    synth = ElevenLabsTTS("local", "local", "local")
    synth.prewarm, synth.reuse_connection = prewarm, reuse
    assert synth.start_warmup() is None and synth._http is None
    await synth.aclose()


async def test_closing_tts_cancels_pending_prewarm_and_closes_client():
    arrived, closed = asyncio.Event(), asyncio.Event()

    class Metadata(httpx.AsyncByteStream):
        async def __aiter__(self):
            arrived.set()
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            closed.set()

    synth = ElevenLabsTTS("local", "local", "local")
    synth.prewarm = synth.reuse_connection = True
    client = synth._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Metadata())))
    warm = synth.start_warmup()
    await asyncio.wait_for(arrived.wait(), 1)
    await asyncio.wait_for(synth.aclose(), 1)
    assert closed.is_set() and warm.cancelled() and client.is_closed and synth._warm_task is None


async def test_total_prewarm_timeout_closes_a_stream_that_never_finishes(monkeypatch):
    closed = asyncio.Event()
    native_wait_for = asyncio.wait_for

    def short_timeout(awaitable, timeout):
        assert timeout == 8  # exercise the production total bound without making the test take eight seconds
        return native_wait_for(awaitable, 0.02)

    class Metadata(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b"unreachable"

        async def aclose(self):
            closed.set()

    def handle(request):
        return httpx.Response(200, stream=Metadata()) if request.method == "GET" else httpx.Response(200, content=b"audio")

    synth = ElevenLabsTTS("local", "local", "local")
    synth.prewarm = synth.reuse_connection = True
    synth._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(asyncio, "wait_for", short_timeout)
    try:
        result = await synth.start_warmup()
        assert result["outcome"] == "failed" and result["error_type"] == "TimeoutError" and closed.is_set()
        assert b"".join([part async for part in synth.audio("hello")]) == b"audio"
    finally:
        await synth.aclose()
