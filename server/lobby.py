"""
Users, tables, and the connections between them.

A user is identified by an id their browser keeps in localStorage, so a refresh or a
dropped connection reattaches them to the same seat, mid-game included.

A table has two seats, NORTH and SOUTH, each empty, a user, or the bot.  Which is
which doesn't matter to the players, who each see themselves at the bottom; the host
takes one and the next to join, or the bot, the other.  The host picks the tiles and
and the time control and starts the match; the match then runs until either player
goes back to the table, to change it and start again, or quits, which closes it.  How
the pair at the table have done is kept until one of them leaves.  A missing player is waited for: the game pauses at
their next choice, though their clock, if the table has one, keeps running.

Everything is in memory, so a server restart ends every table.
"""

import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass, field

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from server.agents import Agent, Human
from server.bots import Bot, DEFAULT_LEVEL, LEVELS
from server.clock import TIME_MODES
from server.config import ALL_TILES, DEFAULT_TILES, TILES_PER_GAME
from server.constants import Player, Tile
from server.game import Tally, play_one_match
from server.seat import Seat

TILE_MODES = ("starter", "random", "custom")
STARTER_TILES = [t for t in ALL_TILES if t in DEFAULT_TILES]

# who sits in a seat: a user id, the bot, or nobody
BOT = "bot"
Occupant = str | None

# users who have been disconnected this long are forgotten, unless mid-match
GRACE_SECONDS = 120

MAX_NAME_LENGTH = 20

# no look-alikes; table ids end up in urls
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _random_id(length: int) -> str:
    return "".join(random.choice(_ALPHABET) for _ in range(length))


def _clean_name(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:MAX_NAME_LENGTH]


@dataclass
class User:
    id: str
    name: str
    websocket: WebSocketServerProtocol | None = None
    table_id: str | None = None
    last_seen: float = field(default_factory=time.monotonic)


@dataclass
class Table:
    id: str
    host_id: str
    seats: dict[Player, Occupant]

    # "starter" plays the default tiles, "random" re-rolls the tiles (and the other
    # game parameters) every game, and "custom" plays the host's pick
    tile_mode: str = "starter"
    tiles: list[Tile] = field(default_factory=lambda: list(STARTER_TILES))

    # one of clock.TIME_MODES
    time_mode: str = "medium"

    # how well the bot plays, if it's seated: one of bots.LEVELS
    bot_level: str = DEFAULT_LEVEL

    # the games won and points scored by whoever's seated; new when that changes
    tally: Tally = field(default_factory=Tally)

    # set when the match starts
    game_seats: dict[Player, Seat] | None = None
    task: asyncio.Task | None = None

    @property
    def playing(self) -> bool:
        return self.task is not None

    def side_of(self, user_id: str) -> Player | None:
        for side, occupant in self.seats.items():
            if occupant == user_id:
                return side
        return None

    def free_side(self) -> Player | None:
        for side, occupant in self.seats.items():
            if occupant is None:
                return side
        return None

    def humans(self) -> list[str]:
        return [o for o in self.seats.values() if o is not None and o != BOT]


class Lobby:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.tables: dict[str, Table] = {}

    # ------------------------------------------------------------ connections

    async def hello(
        self, websocket: WebSocketServerProtocol, user_id: object, name: object
    ) -> User:
        """A socket introduced itself.  Returning users keep their table and seat."""
        user = self.users.get(user_id) if isinstance(user_id, str) else None
        if user is None:
            user = User(id=str(uuid.uuid4()), name=_clean_name(name))
            self.users[user.id] = user
        elif _clean_name(name):
            user.name = _clean_name(name)

        old = user.websocket
        user.websocket = websocket
        user.last_seen = time.monotonic()
        if old is not None and old is not websocket:
            # the same user opened another tab; the newest one wins
            # the client doesn't reconnect after this close code
            await old.close(code=4000, reason="replaced")

        await self._send(
            user, {"type": "welcome", "playerId": user.id, "name": user.name}
        )

        table = self._table_of(user)
        if table is None:
            await self._send(user, self._lobby_event())
            return user

        await self._push_table(table)
        side = table.side_of(user.id)
        if table.game_seats is not None and side is not None:
            await table.game_seats[side].attach(websocket)
        return user

    async def disconnect(self, user: User, websocket: WebSocketServerProtocol) -> None:
        if user.websocket is not websocket:
            # already replaced by a newer socket
            return
        user.websocket = None
        user.last_seen = time.monotonic()
        table = self._table_of(user)
        if table is None:
            return
        side = table.side_of(user.id)
        if table.game_seats is not None and side is not None:
            table.game_seats[side].detach(websocket)
        await self._push_table(table)

    async def handle(self, user: User, event: dict) -> None:
        """One message from a user's socket, after hello."""
        user.last_seen = time.monotonic()

        if "choiceId" in event:
            # a click during the game
            table = self._table_of(user)
            side = table.side_of(user.id) if table else None
            if table and table.game_seats is not None and side is not None:
                table.game_seats[side].receive(event)
            return

        kind = event.get("type")
        if kind == "setName":
            await self._set_name(user, event.get("name"))
        elif kind == "createTable":
            await self._create_table(user, event.get("bot") is True)
        elif kind == "joinTable":
            await self._join_table(user, event.get("tableId"))
        elif kind == "leaveTable":
            await self._leave_table(user)
        elif kind == "quit":
            await self._quit(user)
        elif kind == "addBot":
            await self._set_bot(user, True)
        elif kind == "removeBot":
            await self._set_bot(user, False)
        elif kind == "setTiles":
            await self._set_tiles(user, event.get("mode"), event.get("tiles"))
        elif kind == "setTime":
            await self._set_time(user, event.get("mode"))
        elif kind == "setBotLevel":
            await self._set_bot_level(user, event.get("level"))
        elif kind == "start":
            await self._start(user)
        else:
            print(f"Ignored {event=}")

    async def reap_forever(self) -> None:
        """Forget users who left and never came back, unless they're mid-match."""
        while True:
            await asyncio.sleep(30)
            cutoff = time.monotonic() - GRACE_SECONDS
            for user in list(self.users.values()):
                if user.websocket is not None or user.last_seen > cutoff:
                    continue
                table = self._table_of(user)
                if table is not None and table.playing:
                    continue
                await self._leave_table(user, quiet=True)
                del self.users[user.id]

    # ----------------------------------------------------------------- users

    async def _set_name(self, user: User, name: object) -> None:
        user.name = _clean_name(name)
        # a name is only shown once you're seated
        table = self._table_of(user)
        if table is not None:
            await self._push_table(table)

    # ---------------------------------------------------------------- tables

    async def _create_table(self, user: User, bot: bool) -> None:
        if not user.name or self._busy(user):
            return
        await self._leave_table(user, quiet=True)
        table = Table(
            id=_random_id(5),
            host_id=user.id,
            seats={Player.N: BOT if bot else None, Player.S: user.id},
        )
        self.tables[table.id] = table
        user.table_id = table.id
        await self._push_table(table)
        await self._push_lobby()

    async def _join_table(self, user: User, table_id: object) -> None:
        if not user.name:
            return
        if user.table_id == table_id:
            table = self._table_of(user)
            assert table is not None
            await self._push_table(table)
            return
        if self._busy(user):
            await self._error(user, "Finish your game first.")
            return

        table = self.tables.get(table_id) if isinstance(table_id, str) else None
        if table is None:
            await self._error(user, "That table is gone.")
            await self._send(user, {"type": "left"})
            await self._send(user, self._lobby_event())
            return
        free = table.free_side()
        if table.playing or free is None:
            await self._error(user, "That table is full.")
            await self._send(user, {"type": "left"})
            await self._send(user, self._lobby_event())
            return

        await self._leave_table(user, quiet=True)
        table.seats[free] = user.id
        table.tally = Tally()
        user.table_id = table.id
        await self._push_table(table)
        await self._push_lobby()

    async def _leave_table(self, user: User, quiet: bool = False) -> None:
        table = self._table_of(user)
        user.table_id = None
        if table is not None:
            if table.playing:
                # a match is only left by quitting it; otherwise the game waits for them
                user.table_id = table.id
                return
            side = table.side_of(user.id)
            if side is not None:
                table.seats[side] = None
                table.tally = Tally()
            humans = table.humans()
            if not humans:
                del self.tables[table.id]
            else:
                if table.host_id == user.id:
                    table.host_id = humans[0]
                await self._push_table(table)

        if not quiet:
            await self._send(user, {"type": "left"})
        await self._push_lobby()

    async def _quit(self, user: User) -> None:
        """End the match for both players, close the table, and send everyone to the lobby."""
        table = self._table_of(user)
        if table is None or not table.playing:
            return
        assert table.task is not None
        table.task.cancel()
        del self.tables[table.id]

        for user_id in table.humans():
            seated = self.users.get(user_id)
            if seated is None:
                continue
            seated.table_id = None
            if seated is not user:
                await self._send(
                    seated, {"type": "error", "message": f"{user.name} quit."}
                )
            await self._send(seated, {"type": "left"})
        await self._push_lobby()

    async def _set_bot(self, user: User, bot: bool) -> None:
        """Seat the bot in the free seat, or take it out of its seat."""
        table = self._table_of(user)
        if table is None or table.playing or table.host_id != user.id:
            return
        if bot:
            side = table.free_side()
            if side is None:
                return
            table.seats[side] = BOT
        else:
            side = table.side_of(BOT)
            if side is None:
                return
            table.seats[side] = None
        table.tally = Tally()
        await self._push_table(table)
        await self._push_lobby()

    async def _set_tiles(self, user: User, mode: object, tiles: object) -> None:
        table = self._table_of(user)
        if table is None or table.playing or table.host_id != user.id:
            return
        if mode not in TILE_MODES or not isinstance(tiles, list):
            return
        if mode == "starter":
            tiles = STARTER_TILES
        try:
            chosen = [Tile(t) for t in tiles]
        except ValueError:
            return
        if any(t not in ALL_TILES for t in chosen) or len(set(chosen)) != len(chosen):
            return
        if len(chosen) > TILES_PER_GAME:
            return
        # a custom pick keeps the order it was picked in, through to the game
        table.tiles = (
            chosen if mode == "custom" else [t for t in ALL_TILES if t in chosen]
        )
        table.tile_mode = str(mode)
        await self._push_table(table)

    async def _set_time(self, user: User, mode: object) -> None:
        table = self._table_of(user)
        if table is None or table.playing or table.host_id != user.id:
            return
        if mode not in TIME_MODES:
            return
        table.time_mode = str(mode)
        await self._push_table(table)

    async def _set_bot_level(self, user: User, level: object) -> None:
        table = self._table_of(user)
        if table is None or table.playing or table.host_id != user.id:
            return
        if level not in LEVELS or level == table.bot_level:
            return
        table.bot_level = str(level)
        # a different bot is a different opponent
        table.tally = Tally()
        await self._push_table(table)

    async def _start(self, user: User) -> None:
        table = self._table_of(user)
        if table is None or table.playing or table.host_id != user.id:
            return
        if any(occupant is None for occupant in table.seats.values()):
            return
        if table.tile_mode != "random" and len(table.tiles) != TILES_PER_GAME:
            return

        seats = {side: Seat() for side in Player}
        agents: dict[Player, Agent] = {}
        names: dict[Player, str] = {}
        for side, occupant in table.seats.items():
            assert occupant is not None
            if occupant == BOT:
                agents[side] = Bot(table.bot_level)
                names[side] = "bot"
            else:
                agents[side] = Human(seats[side])
                names[side] = self.users[occupant].name

        table.game_seats = seats
        tiles = None if table.tile_mode == "random" else list(table.tiles)
        table.task = asyncio.create_task(self._run_match(table, agents, tiles, names))
        table.task.add_done_callback(_report_crash)

        # switch both screens to the board before the game's first messages
        await self._push_table(table)
        await self._push_lobby()
        for side, occupant in table.seats.items():
            seated = self.users.get(occupant) if occupant else None
            if seated is not None and seated.websocket is not None:
                await seats[side].attach(seated.websocket)

    async def _run_match(
        self,
        table: Table,
        agents: dict[Player, Agent],
        tiles: list[Tile] | None,
        names: dict[Player, str],
    ) -> None:
        """Play the match, then, unless it was quit, bring everyone back to the table."""
        await play_one_match(agents, tiles, names, table.time_mode, table.tally)
        table.task = None
        table.game_seats = None
        await self._push_table(table)
        await self._push_lobby()

    # ------------------------------------------------------------- plumbing

    def _table_of(self, user: User) -> Table | None:
        return self.tables.get(user.table_id) if user.table_id else None

    def _busy(self, user: User) -> bool:
        """True if the user is seated at a match in progress."""
        table = self._table_of(user)
        return table is not None and table.playing

    def _table_event(self, table: Table, user_id: str) -> dict:
        seats: dict[str, dict | None] = {}
        for side, occupant in table.seats.items():
            if occupant is None:
                seats[side.value] = None
            elif occupant == BOT:
                seats[side.value] = {"name": "bot", "bot": True, "connected": True}
            else:
                user = self.users.get(occupant)
                seats[side.value] = {
                    "name": user.name if user else "",
                    "bot": False,
                    "connected": user is not None and user.websocket is not None,
                }
        my_side = table.side_of(user_id)
        return {
            "type": "table",
            "table": {
                "id": table.id,
                "playing": table.playing,
                "seats": seats,
                "mode": table.tile_mode,
                "tiles": table.tiles,
                "time": table.time_mode,
                "botLevel": table.bot_level,
                "mySide": my_side.value if my_side else None,
                "amHost": table.host_id == user_id,
            },
        }

    def _lobby_event(self) -> dict:
        """The tables with a free seat."""
        tables = []
        for table in self.tables.values():
            if table.playing or None not in table.seats.values():
                continue
            names: dict[str, str | None] = {}
            for side, occupant in table.seats.items():
                if occupant is None:
                    names[side.value] = None
                elif occupant == BOT:
                    names[side.value] = "bot"
                else:
                    user = self.users.get(occupant)
                    names[side.value] = user.name if user else ""
            tables.append(
                {
                    "id": table.id,
                    "seats": names,
                    "mode": table.tile_mode,
                    "tiles": table.tiles,
                }
            )
        return {"type": "lobby", "tables": tables}

    async def _push_table(self, table: Table) -> None:
        for user_id in table.humans():
            user = self.users.get(user_id)
            if user is not None:
                await self._send(user, self._table_event(table, user_id))

    async def _push_lobby(self) -> None:
        event = self._lobby_event()
        for user in list(self.users.values()):
            if user.table_id is None:
                await self._send(user, event)

    async def _error(self, user: User, message: str) -> None:
        await self._send(user, {"type": "error", "message": message})

    async def _send(self, user: User, event: dict) -> None:
        websocket = user.websocket
        if websocket is None:
            return
        try:
            await websocket.send(json.dumps(event))
        except ConnectionClosed:
            pass


def _report_crash(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        task.print_stack()
