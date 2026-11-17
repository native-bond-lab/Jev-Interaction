"""Optional Doubao measurement stack: protocol, streaming, failure and resource ownership without credentials."""
import asyncio
import base64
import gzip
import json
import struct

import httpx
import pytest

from jev_interaction.adapters import registry
from jev_interaction.adapters.doubao import auth_headers
from jev_interaction.adapters.doubao_asr import DoubaoRealtime, Utterances, packet, unpack
from jev_interaction.adapters.doubao_tts import DoubaoTTS


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    for name in ("DOUBAO_API_KEY", "DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOUBAO_API_KEY", "private-speech-key")
    monkeypatch.setenv("DOUBAO_ASR_RESOURCE_ID", "test-asr-resource")
    monkeypatch.setenv("DOUBAO_TTS_RESOURCE_ID", "test-tts-resource")
    monkeypatch.setenv("DOUBAO_TTS_VOICE", "test-voice")


def response(event, flags=1, compress=True):
    payload = json.dumps(event).encode()
    if compress:
        payload = gzip.compress(payload)
    return bytes([0x11, 0x90 | flags, 0x11 if compress else 0x10, 0]) + (
        struct.pack(">i", -1 if flags == 3 else 1) if flags & 1 else b"") + struct.pack(">I", len(payload)) + payload


def utterance(text, start, end, final=True):
    return {"text": text, "start_time": start, "end_time": end, "definite": final}


def test_new_and_legacy_voice_authentication(monkeypatch):
    assert auth_headers(asr=True) == {"X-Api-Key": "private-speech-key"}
    monkeypatch.delenv("DOUBAO_API_KEY")
    with pytest.raises(ValueError):
        auth_headers()
    monkeypatch.setenv("DOUBAO_APP_ID", "app")
    monkeypatch.setenv("DOUBAO_ACCESS_TOKEN", "token")
    assert auth_headers(asr=True) == {"X-Api-App-Key": "app", "X-Api-Access-Key": "token"}
    assert auth_headers() == {"X-Api-App-Id": "app", "X-Api-Access-Key": "token"}


@pytest.mark.parametrize("flags", [0, 1, 2, 3])
@pytest.mark.parametrize("compress", [True, False])
def test_asr_binary_protocol_headers_and_compression(flags, compress):
    event = {"result": {"text": "你好", "utterances": []}}
    assert unpack(response(event, flags, compress)) == (event, bool(flags & 2))
    audio = packet(b"\x00\x01" * 3200, audio=True, last=True)
    assert audio[:4] == bytes([0x11, 0x22, 1, 0])
    assert struct.unpack(">I", audio[4:8])[0] == len(audio) - 8
    assert gzip.decompress(audio[8:]) == b"\x00\x01" * 3200


def test_asr_repeated_full_snapshots_and_corrected_partial_do_not_duplicate_finals():
    parser = Utterances()
    def feed(*items):
        return [(s.text, s.final) for s in parser.feed({"result": {"utterances": list(items)}})]
    assert feed(utterance("你", 0, 80, False)) == [("你", False)]
    assert feed(utterance("你好", 0, 150, False)) == [("你好", False)]
    assert feed(utterance("你好。", 0, 200)) == [("你好。", True)]
    assert feed(utterance("你好。", 0, 200)) == []
    assert feed(utterance("你好呀。", 0, 210), utterance("再见", 300, 450, False)) == [("再见", False)]
    assert feed(utterance("你好呀。", 0, 210), utterance("再见。", 300, 500)) == [("再见。", True)]
    assert feed(utterance("再见。", 300, 500), utterance("再见。", 600, 800)) == [("再见。", True)]


@pytest.mark.parametrize("raw", [b"bad", response({})[:-1], bytes([0x11, 0xF0, 0, 0]) + struct.pack(">II", 45000001, 0)])
def test_asr_invalid_packets_and_provider_error_are_bounded(raw):
    with pytest.raises(RuntimeError) as caught:
        unpack(raw)
    assert "private" not in str(caught.value)


class FakeSocket:
    def __init__(self, ack=None):
        self.sent, self.closed = [], False
        self.q = asyncio.Queue()
        self.q.put_nowait(ack if ack is not None else response({}))

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return await self.q.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.q.get()
        if value is None:
            raise StopAsyncIteration
        return value

    async def close(self):
        self.closed = True


async def test_asr_call_lifetime_partial_final_and_cleanup(monkeypatch):
    import jev_interaction.adapters.doubao_asr as module
    ws, connect_args = FakeSocket(), []
    async def connect(url, **kwargs):
        connect_args.append((url, kwargs))
        return ws
    monkeypatch.setattr(module.websockets, "connect", connect)
    asr = DoubaoRealtime()
    try:
        await asr.connect()
        assert len(connect_args) == 1
        assert connect_args[0][1]["additional_headers"]["X-Api-Key"] == "private-speech-key"
        config = json.loads(gzip.decompress(ws.sent[0][8:]))
        assert config["request"]["end_window_size"] == 400 and config["request"]["show_utterances"]
        assert config["audio"]["rate"] == 16000
        await asr.send(b"pcm")
        assert gzip.decompress(ws.sent[1][8:]) == b"pcm"
        ws.q.put_nowait(response({"result": {"utterances": [utterance("你好。", 0, 200)]}}))
        stream = asr.segments()
        segment = await asyncio.wait_for(anext(stream), 1)
        assert segment.text == "你好。" and segment.final
        await stream.aclose()
    finally:
        await asr.close()
    assert ws.closed and asr.task.done() and ws.sent[-1][1] == 0x22


async def test_asr_invalid_ack_closes_socket_and_receive_failure_reaches_consumer(monkeypatch):
    import jev_interaction.adapters.doubao_asr as module
    ws = FakeSocket(b"bad")
    async def connect(*args, **kwargs):
        return ws
    monkeypatch.setattr(module.websockets, "connect", connect)
    asr = DoubaoRealtime()
    with pytest.raises(RuntimeError):
        await asr.connect()
    assert ws.closed
    ws, asr = FakeSocket(), DoubaoRealtime()
    await asr.connect()
    ws.q.put_nowait(b"bad")
    try:
        with pytest.raises(RuntimeError, match="receive failed"):
            await asyncio.wait_for(anext(asr.segments()), 1)
        with pytest.raises(RuntimeError):
            await asr.send(b"pcm")
    finally:
        await asr.close()


def audio_event(chunk):
    return ("data: " + json.dumps({"code": 0, "data": base64.b64encode(chunk).decode()}) + "\n\n").encode()


async def test_tts_delivers_before_eof_reuses_client_and_closes_cancelled_stream():
    release, closed = asyncio.Event(), asyncio.Event()
    requests = []
    class Audio(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield audio_event(b"first")
            await release.wait()
            yield audio_event(b"last") + b'data: {"code":20000000,"data":null}\n\n'
        async def aclose(self):
            closed.set()
    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=Audio())
    synth = DoubaoTTS()
    client = synth._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    stream = synth.audio("private speech")
    try:
        assert await asyncio.wait_for(anext(stream), 1) == b"first"
        assert not release.is_set()
        await stream.aclose()
        assert closed.is_set() and not client.is_closed
        release.set()
        assert b"".join([part async for part in synth.audio("next")]) == b"firstlast"
        assert requests[0].headers["X-Api-Key"] == "private-speech-key"
        assert json.loads(requests[0].content)["req_params"]["audio_params"]["format"] == "mp3"
    finally:
        await stream.aclose()
        await synth.aclose()
    assert client.is_closed


@pytest.mark.parametrize("content", [b'data: {"code":45000001,"message":"private body"}\n\n',
    b'data: {"code":0,"data":"invalid base64!"}\n\n', audio_event(b"partial")])
async def test_tts_errors_and_truncated_completion_never_echo_provider_body(content):
    synth = DoubaoTTS()
    synth._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content)))
    try:
        with pytest.raises(RuntimeError) as caught:
            _ = [chunk async for chunk in synth.audio("private speech")]
        assert "private" not in str(caught.value)
    finally:
        await synth.aclose()


def test_optional_registry_and_credentials_do_not_change_defaults(monkeypatch):
    assert isinstance(registry.create("asr", name="doubao"), DoubaoRealtime)
    assert isinstance(registry.create("tts", name="doubao"), DoubaoTTS)
    monkeypatch.setenv("ASR_PROVIDER", "doubao")
    monkeypatch.setenv("TTS_PROVIDER", "doubao")
    missing = registry.missing_settings()
    assert not any(name.startswith("DOUBAO_") for name in missing)
