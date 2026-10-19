import asyncio

from server import clock
from server.agents import Human
from server.bots import Bot
from server.clock import TimeControl
from server.constants import Player, OutEventType
from server.game import play_one_game
from server.seat import Seat


class SilentSeat(Seat):
    """A player who never answers, keeping what they're sent."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict] = []

    async def send(self, event: dict) -> None:
        self.sent.append(event)


def test_a_game_plays_itself_out_on_defaults(monkeypatch):
    # south never chooses anything, so every decision of theirs falls to the clock's
    # defaults: random moves, accepting the bot's claims, keeping the exchange, and
    # random smites, losses and replacements; the game must still come to an end
    monkeypatch.setitem(
        clock.TIME_CONTROLS, "test", TimeControl(reserve=0.02, main=0.002, minor=0.001)
    )
    monkeypatch.setattr(clock, "LAG_GRACE", 0)
    seats = {player: SilentSeat() for player in Player}
    players = {Player.N: Bot("easy", delay=0), Player.S: Human(seats[Player.S])}
    names = {Player.N: "n", Player.S: "s"}

    score, _ = asyncio.run(
        asyncio.wait_for(
            play_one_game(
                {Player.N: 0, Player.S: 0}, players, None, Player.S, names, "test"
            ),
            timeout=60,
        )
    )
    assert sum(score.values()) > 0

    clocks = [e for e in seats[Player.S].sent if e["type"] == OutEventType.CLOCK]
    # south's reserve ran out on their first decision, and stayed out
    assert clocks[0]["reserve"]["south"] == 20
    assert clocks[-1]["reserve"]["south"] == 0
