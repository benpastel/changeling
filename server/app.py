#!/usr/bin/env python3

import asyncio
import json
import mimetypes
import os
import signal
from http import HTTPStatus
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from server.lobby import Lobby, User


LOBBY = Lobby()


async def handler(websocket: WebSocketServerProtocol) -> None:
    """
    One browser tab's connection.

    The first message must be a hello identifying the user; every message after that
    is a lobby request or a click in their game.  When the socket closes the user
    keeps their seat, so they can reconnect into it.
    """
    user: User | None = None
    try:
        async for message in websocket:
            try:
                event = json.loads(message)
                if user is None:
                    if event.get("type") == "hello":
                        user = await LOBBY.hello(
                            websocket, event.get("playerId"), event.get("name")
                        )
                    continue
                await LOBBY.handle(user, event)
            except ConnectionClosed:
                raise
            except Exception as e:
                # a malformed message shouldn't drop the connection
                print(f"Ignored {message=}: {e!r}")
    except ConnectionClosed:
        pass
    finally:
        if user is not None:
            await LOBBY.disconnect(user, websocket)


DOCS = Path(__file__).resolve().parent.parent / "docs"


async def process_request(path: str, request_headers: Any) -> tuple | None:
    """
    Plain HTTP: render's health check and the client's static files.
    Websocket upgrades return None and proceed to the handshake.
    """
    if path == "/healthz":
        return HTTPStatus.OK, [], b"OK\n"
    if request_headers.get("Upgrade", "").lower() == "websocket":
        return None
    return _static(path)


def _static(path: str) -> tuple:
    name = path.split("?", 1)[0].split("#", 1)[0].lstrip("/") or "index.html"
    file = (DOCS / name).resolve()
    if file.parent != DOCS or not file.is_file():
        return HTTPStatus.NOT_FOUND, [], b"Not found\n"
    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type.endswith("javascript"):
        content_type += "; charset=utf-8"
    headers = [("Content-Type", content_type), ("Cache-Control", "no-cache")]
    return HTTPStatus.OK, headers, file.read_bytes()


async def main() -> None:
    # render sends SIGTERM when shutting down an instance; listen & exit gracefully
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    port = int(os.environ.get("PORT", "8001"))
    print(f"Serving websocket server on port {port}.")

    reaper = asyncio.create_task(LOBBY.reap_forever())
    async with serve(handler, "", port, process_request=process_request):
        await stop
    reaper.cancel()


if __name__ == "__main__":
    asyncio.run(main())
