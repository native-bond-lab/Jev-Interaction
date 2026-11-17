"""Shared synthesis, first-byte delivery, cancellation and resource limits; never uses a paid provider."""
import asyncio
import threading
from collections import OrderedDict

import pytest

from jev_interaction.server.audio import AudioGone, AudioLimitError, CallAudio


class GatedVoice:
    media_type = "audio/mpeg"

    def __init__(self, prefix=b"first"):
        self.started, self.release, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.calls = 0
        self.prefix = prefix

    async def audio(self, text):
        self.calls += 1
        self.started.set()
        try:
            yield self.prefix
            await self.release.wait()
            yield b"-last"
        finally:
            self.closed.set()


async def test_prefetch_stream_and_range_share_one_incremental_synthesis():
    voice, store = GatedVoice(), CallAudio()
    line = store.add("one", "hello", voice, 1)
    a, b = line.audio("hello"), line.audio("hello")
    try:
        await asyncio.wait_for(voice.started.wait(), 1)  # began before the browser asked for it
        assert await anext(a) == await anext(b) == b"first"
        whole = asyncio.create_task(line.whole())
        await asyncio.sleep(0)
        assert not whole.done() and not voice.release.is_set()
        voice.release.set()
        assert b"".join([chunk async for chunk in a]) == b"-last"
        assert b"".join([chunk async for chunk in b]) == b"-last"
        assert await whole == b"first-last"
        assert await line.whole() == b"first-last"
        assert voice.calls == 1
    finally:
        await a.aclose()
        await b.aclose()
        await store.close()
    assert voice.closed.is_set() and store.bytes == 0


@pytest.mark.parametrize("prefetch", [True, False])
async def test_only_first_reply_line_is_prefetched_and_switch_restores_lazy_start(prefetch):
    voice, store = GatedVoice(), CallAudio(prefetch=prefetch)
    first = store.add("one", "hello", voice, 1)
    second = store.add("two", "again", voice, 1)
    try:
        assert (first.task is not None) is prefetch
        assert second.task is None
        voice.release.set()
        assert await first.whole() == await second.whole() == b"first-last"
        assert voice.calls == 2
    finally:
        await store.close()


async def test_one_disconnected_reader_does_not_cancel_shared_audio():
    voice, store = GatedVoice(), CallAudio()
    line = store.add("one", "hello", voice, 1)
    gone = asyncio.create_task(line.whole())
    try:
        await asyncio.wait_for(voice.started.wait(), 1)
        gone.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gone
        assert not voice.closed.is_set()
        voice.release.set()
        assert await line.whole() == b"first-last" and voice.calls == 1
    finally:
        await store.close()


async def test_stop_closes_old_voice_and_wakes_readers_without_touching_new_generation():
    old, new, dropped = GatedVoice(b"old"), GatedVoice(b"new"), []
    store = CallAudio(dropped.append)
    a = store.add("old", "hello", old, 1)
    b = store.add("new", "hello", new, 2)
    waiting = asyncio.create_task(a.whole())
    try:
        await asyncio.wait_for(old.started.wait(), 1)
        store.cancel_before(2)
        with pytest.raises(AudioGone):
            await asyncio.wait_for(waiting, 1)
        await asyncio.wait_for(old.closed.wait(), 1)
        assert dropped == ["old"] and not b.cancelled
        new.release.set()
        assert await b.whole() == b"new-last"
    finally:
        await store.close()


async def test_finish_line_keeps_acknowledged_playing_line_and_releases_queued_audio():
    voice, store = GatedVoice(), CallAudio(prefetch=False)
    a = store.add("playing", "hello", voice, 1)
    b = store.add("queued", "hello", voice, 1)
    store.finish_line(1, None)
    assert not a.cancelled and not b.cancelled
    store.finish_line(1, "playing")
    assert not a.cancelled and b.cancelled
    await store.close()


async def test_bounded_line_cache_evicts_and_cancels_pending_work():
    voice, dropped = GatedVoice(), []
    store = CallAudio(dropped.append, max_lines=1)
    a = store.add("old", "hello", voice, 1)
    try:
        await asyncio.wait_for(voice.started.wait(), 1)
        store.add("new", "hello", voice, 2)
        assert a.cancelled and dropped == ["old"] and len(store.lines) == 1
        await asyncio.wait_for(voice.closed.wait(), 1)
    finally:
        await store.close()


async def test_byte_limits_fail_closed_and_do_not_repeat_provider_request():
    voice, store = GatedVoice(b"oversized"), CallAudio(max_line_bytes=4)
    line = store.add("one", "hello", voice, 1)
    try:
        for _ in range(2):
            with pytest.raises(AudioLimitError):
                await asyncio.wait_for(line.whole(), 1)
        assert store.bytes == 0 and voice.closed.is_set() and voice.calls == 1
    finally:
        await store.close()


async def test_total_budget_preserves_active_reader_instead_of_growing_unbounded():
    voice, store = GatedVoice(), CallAudio(max_bytes=8, max_line_bytes=100)
    a = store.add("one", "hello", voice, 1)
    reader = a.audio("hello")
    try:
        assert await anext(reader) == b"first"
        b = store.add("two", "hello", voice, 2)
        with pytest.raises(AudioLimitError):
            await asyncio.wait_for(b.whole(), 1)
        assert store.bytes == 5 and not a.cancelled
    finally:
        await reader.aclose()
        await store.close()


async def test_cache_pressure_does_not_evict_current_audio_reader():
    voice, store = GatedVoice(), CallAudio(max_lines=1)
    line = store.add("playing", "hello", voice, 1)
    reader = line.audio("hello")
    try:
        assert await anext(reader) == b"first"
        with pytest.raises(AudioLimitError):
            store.add("queued", "hello", voice, 2)
        assert not line.cancelled and list(store.lines) == ["playing"]
    finally:
        await reader.aclose()
        await store.close()


async def test_provider_concurrency_is_bounded_and_queued_work_cancels_on_close():
    voice, store = GatedVoice(), CallAudio(concurrency=2)
    for index in range(4):
        store.add(str(index), "hello", voice, index)
    await asyncio.wait_for(voice.started.wait(), 1)
    for _ in range(5):
        await asyncio.sleep(0)
    assert voice.calls == 2
    await store.close()
    assert not store.tasks and store.bytes == 0


async def test_expiry_cancels_abandoned_prefetch():
    voice, store = GatedVoice(), CallAudio(ttl=0.02)
    line = store.add("one", "hello", voice, 1)
    try:
        await asyncio.wait_for(voice.closed.wait(), 1)
        assert line.cancelled and store.bytes == 0 and not store.lines
    finally:
        await store.close()


async def test_stream_and_range_http_requests_share_one_synthesis(monkeypatch):
    import httpx

    from jev_interaction.server import app as server

    voice, store = GatedVoice(), CallAudio()
    line = store.add("shared", "hello", voice, 1)
    monkeypatch.setattr(server, "LINES", OrderedDict({"shared": ("hello", line)}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://local") as client:
        try:
            a = asyncio.create_task(client.get("/tts/shared"))
            b = asyncio.create_task(client.get("/tts/shared", headers={"range": "bytes=0-1"}))
            await asyncio.wait_for(voice.started.wait(), 1)
            voice.release.set()
            plain, probe = await asyncio.gather(a, b)
            assert plain.content == b"first-last" and plain.status_code == 200
            assert probe.content == b"fi" and probe.headers["content-range"] == "bytes 0-1/10"
            assert (await client.get("/tts/shared", headers={"range": "bytes=2-"})).content == b"rst-last"
            assert (await client.get("/tts/shared", headers={"range": "bytes=-4"})).content == b"last"
            assert (await client.get("/tts/shared", headers={"range": "bytes=100-"})).status_code == 416
            assert (await client.get("/tts/shared", headers={"range": "bytes=0-"})).content == b"first-last"
            assert voice.calls == 1
        finally:
            await store.close()


async def test_failed_range_synthesis_is_not_billed_again(monkeypatch):
    import httpx

    from jev_interaction.server import app as server

    class FailingVoice:
        media_type = "audio/mpeg"
        calls = 0

        async def audio(self, text):
            self.calls += 1
            raise RuntimeError("test provider failed")
            yield b"unreachable"

    voice, store = FailingVoice(), CallAudio()
    line = store.add("broken", "hello", voice, 1)
    monkeypatch.setattr(server, "LINES", OrderedDict({"broken": ("hello", line)}))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://local") as client:
            for _ in range(2):
                assert (await client.get("/tts/broken", headers={"range": "bytes=0-1"})).status_code == 502
        assert voice.calls == 1
    finally:
        await store.close()


def test_websocket_prefetch_stop_and_disconnect_close_audio_and_pool(monkeypatch):
    from fastapi.testclient import TestClient

    from jev_interaction.server import app as server
    from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeVAD

    started, old_closed, pool_closed = threading.Event(), threading.Event(), threading.Event()
    sessions = []
    session_type = server.Session

    class Session(session_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

    class Responder:
        async def lines(self, messages, max_tokens=160):
            yield "Hello."

    class Voice:
        media_type = "audio/mpeg"
        active = 0
        calls = 0

        async def audio(self, text):
            self.active += 1
            self.calls += 1
            call = self.calls
            started.set()
            try:
                yield b"first"
                await asyncio.Event().wait()
            finally:
                self.active -= 1
                if call == 1:
                    old_closed.set()

        async def aclose(self):
            assert self.active == 0
            pool_closed.set()

    voice = Voice()
    factories = {"judge": FakeJudge, "asr": FakeRecognizer, "llm": Responder, "tts": lambda: voice}
    monkeypatch.setattr(server.registry, "create", lambda kind, **_: factories[kind]())
    monkeypatch.setattr(server.registry, "missing_settings", lambda: [])
    monkeypatch.setattr(server, "best_vad", FakeVAD)
    monkeypatch.setattr(server, "Session", Session)
    monkeypatch.setenv("TTS_PREFETCH", "1")
    for name, value in {"MAX_CALLS": 0, "MAX_CALL_S": 0, "DAY_BUDGET_S": 0, "RECORD": False,
                        "EMBEDDER": None, "LINES": OrderedDict()}.items():
        monkeypatch.setattr(server, name, value)
    with TestClient(server.app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "start", "profile": "companion", "language": "en"})
        first = socket.receive_json()
        assert first["type"] == "line" and started.wait(timeout=2)
        client.portal.call(sessions[0]._stop_line)
        while socket.receive_json()["type"] != "stop":
            pass
        assert old_closed.wait(timeout=2)
        assert client.get(first["audio"]).status_code == 404
    assert pool_closed.wait(timeout=2) and not server.LINES


async def test_settings_tts_probe_closes_early_stream_and_optional_pool():
    from jev_interaction.server import settings

    class Voice:
        stream_closed = pool_closed = False

        async def audio(self, text):
            try:
                yield b"first"
                raise AssertionError("probe must stop after its first chunk")
            finally:
                self.stream_closed = True

        async def aclose(self):
            assert self.stream_closed
            self.pool_closed = True

    voice = Voice()
    result = await settings.test("tts", None, lambda _: voice)
    assert result["ok"] and voice.pool_closed


def test_server_prewarm_runs_while_asr_connect_is_pending_and_closes_on_start_failure(monkeypatch):
    from fastapi.testclient import TestClient

    from jev_interaction.server import app as server
    from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeResponder, FakeVAD

    warm_started, warm_closed, pool_closed = threading.Event(), threading.Event(), threading.Event()

    class Voice:
        task = None

        def start_warmup(self):
            async def run():
                warm_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    warm_closed.set()

            self.task = asyncio.create_task(run())

        async def aclose(self):
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            pool_closed.set()

    class Recognizer(FakeRecognizer):
        async def connect(self):
            # The warm task must run BEFORE ASR setup returns, rather than await call setup completion.
            for _ in range(100):
                if warm_started.is_set():
                    raise RuntimeError("intentional test-only ASR rejection")
                await asyncio.sleep(0.001)
            raise AssertionError("TTS warmup did not overlap ASR setup")

    voice = Voice()
    factories = {"judge": FakeJudge, "asr": Recognizer, "llm": FakeResponder, "tts": lambda: voice}
    monkeypatch.setattr(server.registry, "create", lambda kind, **_: factories[kind]())
    monkeypatch.setattr(server.registry, "missing_settings", lambda: [])
    monkeypatch.setattr(server, "best_vad", FakeVAD)
    for name, value in {"MAX_CALLS": 0, "MAX_CALL_S": 0, "DAY_BUDGET_S": 0, "RECORD": False,
                        "EMBEDDER": None}.items():
        monkeypatch.setattr(server, name, value)
    with TestClient(server.app) as client, client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "start", "profile": "companion", "language": "en"})
        event = socket.receive_json()
        assert event["type"] == "error" and event["what"] == "start" and "intentional" in event["text"]
    assert warm_started.is_set() and warm_closed.is_set() and pool_closed.is_set()
