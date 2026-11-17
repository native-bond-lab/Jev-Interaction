"""An idle gap expires the old Jev socket; the retained socket preserves identical requests."""
import asyncio
import json

import httpx

from jev_interaction.judge import JevClient


async def test_judge_reuses_socket_after_caller_pause_without_changing_request(monkeypatch):
    accepted, requests, writers, handlers = 0, [], set(), set()
    response = json.dumps({"answers": {"done": {"choice": "finished"}}}).encode()

    async def handle(reader, writer):
        nonlocal accepted
        accepted += 1
        connection = accepted
        writers.add(writer)
        handlers.add(asyncio.current_task())
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                headers = dict(line.split(b":", 1) for line in head.split(b"\r\n")[1:] if b":" in line)
                body = await reader.readexactly(int(headers[b"Content-Length"]))
                requests.append((connection, head.split(b"\r\n")[0], headers[b"Authorization"], json.loads(body)))
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(response)).encode() + b"\r\n\r\n" + response)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            writers.discard(writer)
            handlers.discard(asyncio.current_task())

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client_type(trust_env=False, **kwargs))
    old = JevClient("local-key", "local-model", f"http://127.0.0.1:{port}/judge", keepalive_expiry=0.01)
    retained = JevClient("local-key", "local-model", f"http://127.0.0.1:{port}/judge")
    questions = {"done": {"type": "choice", "criteria": {"finished": "The user is finished."}}}
    try:
        for client in (old, retained):
            assert await client.ask(questions, "same-state") == {"done": {"choice": "finished"}}
        await asyncio.sleep(0.03)  # scaled idle-expiry control; production 5 s vs 60 s is measured separately
        for client in (old, retained):
            assert await client.ask(questions, "same-state") == {"done": {"choice": "finished"}}
        assert [request[0] for request in requests] == [1, 2, 3, 2]
        assert all(request[1:] == requests[0][1:] for request in requests)
        assert requests[0][3] == {"model": "local-model", "questions": questions, "state": "same-state"}
    finally:
        await old.aclose()
        await retained.aclose()
        server.close()
        await server.wait_closed()
        for writer in list(writers):
            writer.close()
        await asyncio.gather(*list(handlers), return_exceptions=True)
    assert old._http.is_closed and retained._http.is_closed
