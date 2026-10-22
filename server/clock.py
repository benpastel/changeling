"""
Move clocks.

Each decision has an allowance: longer for choosing your action, shorter for everything
else (whether to challenge, what to lose, the exchange...).  Time past the allowance
comes out of a reserve that lasts the game.  Once both are gone the game decides for
the player, with the defaults in game.py, and carries on; nobody loses on time.

The clock is the game's, per table, but the game's functions all reach it through
`decide`, which finds the current game's clock in a context variable: each match runs
in its own task, so each sees its own.

Either player can pause the match, e.g. while the tutorial shows them around the board.
Paused, the clock stops, and nothing anyone decides (the bot included) takes effect
until it's resumed.
"""

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from server.constants import OutEventType, Player
from server.seat import Seat

T = TypeVar("T")


@dataclass(frozen=True)
class TimeControl:
    reserve: float
    main: float
    minor: float


# "unlimited" has no clock at all
TIME_CONTROLS = {
    "fast": TimeControl(reserve=60, main=10, minor=5),
    "medium": TimeControl(reserve=120, main=20, minor=10),
    "slow": TimeControl(reserve=240, main=40, minor=20),
}
UNLIMITED = "unlimited"
TIME_MODES = (*TIME_CONTROLS, UNLIMITED)

# a click sent just before the deadline still counts, if it's this late in arriving
LAG_GRACE = 0.5


class Pause:
    """Who has paused the match; it's paused while anyone has."""

    def __init__(self) -> None:
        self.by: set[Player] = set()
        self._running = asyncio.Event()
        self._running.set()
        self._paused = asyncio.Event()

    @property
    def paused(self) -> bool:
        return bool(self.by)

    def set(self, player: Player, on: bool) -> None:
        if on:
            self.by.add(player)
        else:
            self.by.discard(player)
        for event, wanted in [
            (self._paused, self.paused),
            (self._running, not self.paused),
        ]:
            if wanted:
                event.set()
            else:
                event.clear()

    async def until_running(self) -> None:
        await self._running.wait()

    async def until_paused(self) -> None:
        await self._paused.wait()


class Clock:
    def __init__(
        self, control: TimeControl, seats: dict[Player, Seat], pause: Pause
    ) -> None:
        self.control = control
        self.seats = seats
        self.pause = pause
        self.reserve = {player: control.reserve for player in Player}

    async def decide(
        self,
        player: Player,
        main: bool,
        choice: Awaitable[T],
        default: Callable[[], T],
    ) -> T:
        allowance = self.control.main if main else self.control.minor
        chosen = asyncio.ensure_future(choice)
        try:
            # the clock runs in stretches between pauses, each spending what's left of
            # the allowance first, then the reserve
            while True:
                await self.pause.until_running()
                started = time.monotonic()
                await self.send(player, allowance)
                paused = asyncio.ensure_future(self.pause.until_paused())
                done, _ = await asyncio.wait(
                    {chosen, paused},
                    timeout=allowance + self.reserve[player] + LAG_GRACE,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                paused.cancel()
                spent = time.monotonic() - started
                over = max(0.0, spent - allowance)
                allowance = max(0.0, allowance - spent)
                self.reserve[player] = max(0.0, self.reserve[player] - over)
                if chosen in done:
                    break
                if not done:
                    self.reserve[player] = 0
                    # their last prompt asked for a choice that's no longer wanted
                    await self.seats[player].send(
                        {"type": OutEventType.PROMPT, "choiceId": 0, "prompt": ""}
                    )
                    await self.send(None, 0)
                    return default()
                # stopped where it is until it's resumed
                await self.send(player, allowance, paused=True)
        finally:
            chosen.cancel()
        await self.send(None, 0)
        return chosen.result()

    async def send(
        self, running: Player | None, allowance: float, paused: bool = False
    ) -> None:
        """
        Both reserves, and whose clock is running: their allowance, then their reserve,
        count down from now, unless `paused`.  Times are in epoch ms; see Seat.attach
        for `sent`.
        """
        now = time.time() * 1000
        event = {
            "type": OutEventType.CLOCK,
            "reserve": {player.value: self.reserve[player] * 1000 for player in Player},
            "running": running,
            "allowanceEnds": now + allowance * 1000,
            "paused": paused,
            "sent": now,
        }
        for seat in self.seats.values():
            await seat.send(event)


_clock: ContextVar[Clock | None] = ContextVar("clock", default=None)
_pause: ContextVar[Pause] = ContextVar("pause")


def start_clock(
    time_mode: str, seats: dict[Player, Seat], pause: Pause | None = None
) -> Clock | None:
    """
    A fresh clock for this game, with the reserves full; None if unlimited.  The game
    pauses with `pause`, if it's given.
    """
    pause = pause or Pause()
    _pause.set(pause)
    control = TIME_CONTROLS.get(time_mode)
    clock = Clock(control, seats, pause) if control else None
    _clock.set(clock)
    return clock


async def decide(
    player: Player,
    main: bool,
    choice: Awaitable[T],
    default: Callable[[], T],
) -> T:
    """
    Wait for `player` to make `choice` on the clock, or take `default()` if they run
    out of time.  `main` is the choice of action; everything else gets the minor
    allowance.  Paused, the choice waits to take effect until the game is resumed.
    """
    clock = _clock.get()
    result = await (
        choice if clock is None else clock.decide(player, main, choice, default)
    )
    pause = _pause.get(None)
    if pause is not None:
        await pause.until_running()
    return result
