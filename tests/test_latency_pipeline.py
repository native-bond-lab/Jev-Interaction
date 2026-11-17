"""Resource cleanup and unchanged awaited startup contract. Withdrawn scheduling tests are archived."""
import asyncio

import httpx
import pytest

from jev_interaction.adapters.elevenlabs_tts import ElevenLabsTTS
from jev_interaction.testing import scripted_session


class SlowResponder:
    def __init__(self):
        self.started, self.release, self.closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.calls = 0

    async def lines(self, messages, max_tokens=160):
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
            yield "Done."
        finally:
            self.closed.set()


async def test_external_response_cancellation_propagates_and_closes_stream():
    session, _, _ = scripted_session()
    slow = session.llm = SlowResponder()
    driver = asyncio.create_task(session.respond("pickup"))
    try:
        await asyncio.wait_for(slow.started.wait(), 1)
        driver.cancel()
        with pytest.raises(asyncio.CancelledError):
            await driver
        assert slow.closed.is_set() and not session.generating
    finally:
        await session.close()


async def test_default_start_keeps_awaited_greeting_contract():
    session, events, _ = scripted_session()
    slow = session.llm = SlowResponder()
    driver = asyncio.create_task(session.start())
    try:
        await asyncio.wait_for(slow.started.wait(), 1)
        assert not driver.done()
        slow.release.set()
        await asyncio.wait_for(driver, 1)
        assert any(event["type"] == "line" for event in events)
    finally:
        await session.close()


@pytest.mark.parametrize("chunk_bytes", ["0", "4096"])
async def test_elevenlabs_forwards_small_first_chunk_before_the_rest(monkeypatch, chunk_bytes):
    class AudioStream(httpx.AsyncByteStream):
        def __init__(self):
            self.release, self.closed = asyncio.Event(), False

        async def __aiter__(self):
            yield b"a" * 128
            await self.release.wait()
            yield b"b" * 4096

        async def aclose(self):
            self.closed = True

    stream, client_type, clients = AudioStream(), httpx.AsyncClient, []

    def client(**kwargs):
        made = client_type(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)), **kwargs)
        clients.append(made)
        return made

    monkeypatch.setenv("ELEVENLABS_TTS_CHUNK_BYTES", chunk_bytes)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    synth = ElevenLabsTTS("test", "test", "test")
    iterator = synth.audio("test")
    first = asyncio.create_task(anext(iterator))
    try:
        if chunk_bytes == "0":
            assert await asyncio.wait_for(asyncio.shield(first), 1) == b"a" * 128
            assert not stream.release.is_set()
        else:
            for _ in range(10):
                await asyncio.sleep(0)
            assert not first.done()
        stream.release.set()
        initial = await asyncio.wait_for(first, 1)
        remaining = b"".join([part async for part in iterator])
        assert initial + remaining == b"a" * 128 + b"b" * 4096
    finally:
        stream.release.set()
        await asyncio.gather(first, return_exceptions=True)
        await iterator.aclose()
        await synth.aclose()
    assert stream.closed and all(client.is_closed for client in clients)
