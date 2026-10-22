"""
A Seat is one side of the board at a table.  The game talks only to seats, never to
websockets, so a player can drop and reconnect (e.g. refresh the page) mid-game without
the game noticing.
"""

import asyncio
import json
import time

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from server.constants import OutEventType

# The latest message of each of these types describes what the player should currently
# see, so it is remembered and replayed to a reconnecting socket, in this order.
# (State first: rendering it rebuilds the action panel, which clears highlights.)
_REPLAYED = [
    OutEventType.STATE_CHANGE,
    OutEventType.SELECTION_CHANGE,
    OutEventType.HIGHLIGHT_CHANGE,
    OutEventType.PROMPT,
    OutEventType.CLOCK,
    OutEventType.PAUSE,
    OutEventType.MATCH_CHANGE,
]


class Seat:
    def __init__(self) -> None:
        self.websocket: WebSocketServerProtocol | None = None

        # incrementing id for each prompt that requires a choice; see choices.py
        self.next_choice_id = 1

        self._latest: dict[OutEventType, str] = {}
        self._inbox: asyncio.Queue[dict] = asyncio.Queue()

        # held while replaying, so a game update can't land in the middle of a replay
        self._lock = asyncio.Lock()

    async def send(self, event: dict) -> None:
        """Send to the attached socket if any; drop it otherwise."""
        message = json.dumps(event)
        kind = OutEventType(event["type"])
        if kind in _REPLAYED:
            self._latest[kind] = message
        async with self._lock:
            await self._send_now(message)

    async def recv(self) -> dict:
        """Wait for the next incoming choice from whichever socket is attached."""
        return await self._inbox.get()

    def receive(self, event: dict) -> None:
        """Called by the connection handler with a choice from the player."""
        self._inbox.put_nowait(event)

    async def attach(self, websocket: WebSocketServerProtocol) -> None:
        async with self._lock:
            self.websocket = websocket
            for kind in _REPLAYED:
                if kind in self._latest:
                    message = self._latest[kind]
                    if kind == OutEventType.CLOCK:
                        # the clock's times are the server's; `sent` lets the browser
                        # allow for its own clock being off, so it must be now
                        message = json.dumps(
                            {**json.loads(message), "sent": time.time() * 1000}
                        )
                    await self._send_now(message)

    def detach(self, websocket: WebSocketServerProtocol) -> None:
        if self.websocket is websocket:
            self.websocket = None

    async def _send_now(self, message: str) -> None:
        websocket = self.websocket
        if websocket is None:
            return
        try:
            await websocket.send(message)
        except ConnectionClosed:
            self.detach(websocket)


class DummySeat(Seat):
    """
    The bot's seat: sends go nowhere.

    This simplifies the game loop; we can always send notifications to a seat
    without checking if it's a human or bot.
    """

    async def send(self, event: dict) -> None:
        pass

    async def recv(self) -> dict:
        raise NotImplementedError("DummySeat should not receive messages")
