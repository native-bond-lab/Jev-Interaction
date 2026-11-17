"""WebSocket client with an aiohttp fallback for preinstalled environments."""
from __future__ import annotations

from collections.abc import Mapping


class _AiohttpWebSocket:
    def __init__(self, session, socket, message_types):
        self._session = session
        self._socket = socket
        self._message_types = message_types

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            message = await self._socket.receive()
            if message.type in (self._message_types.TEXT, self._message_types.BINARY):
                return message.data
            if message.type == self._message_types.ERROR:
                error = self._socket.exception()
                if error:
                    raise error
                raise OSError("WebSocket connection failed")
            if message.type in (self._message_types.CLOSE, self._message_types.CLOSED, self._message_types.CLOSING):
                raise StopAsyncIteration

    async def send(self, data: str | bytes):
        if isinstance(data, str):
            await self._socket.send_str(data)
        else:
            await self._socket.send_bytes(data)

    async def close(self):
        try:
            await self._socket.close()
        finally:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()


async def connect(
    uri: str,
    *,
    additional_headers: Mapping[str, str] | None = None,
    max_size: int | None = None,
    **kwargs,
):
    try:
        import websockets
    except ModuleNotFoundError as exc:
        if exc.name != "websockets":
            raise
    else:
        return await websockets.connect(uri, additional_headers=additional_headers, max_size=max_size, **kwargs)

    import aiohttp

    session = aiohttp.ClientSession()
    try:
        socket = await session.ws_connect(
            uri,
            headers=additional_headers,
            max_msg_size=0 if max_size is None else max_size,
            **kwargs,
        )
    except BaseException:
        await session.close()
        raise
    return _AiohttpWebSocket(session, socket, aiohttp.WSMsgType)
