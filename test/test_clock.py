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


def test_a_pause_stops_the_clock_and_holds_the_choice(monkeypatch):
    # south chooses during the pause, so after their allowance would be gone; the
    # clock stands still meanwhile, and the choice waits for the resume to count
    monkeypatch.setattr(clock, "LAG_GRACE", 0)
    seats = {player: SilentSeat() for player in Player}

    async def play():
        pause = clock.Pause()
        timer = clock.start_clock("fast", seats, pause)
        assert timer is not None
        timer.control = TimeControl(reserve=0.2, main=0.1, minor=0.1)
        timer.reserve = {player: 0.2 for player in Player}
        chosen = asyncio.get_running_loop().create_future()
        deciding = asyncio.create_task(
            clock.decide(Player.S, True, chosen, lambda: "default")
        )
        await asyncio.sleep(0.05)
        pause.set(Player.N, True)
        await asyncio.sleep(0.4)
        chosen.set_result("chosen")
        await asyncio.sleep(0.05)
        assert not deciding.done()
        pause.set(Player.N, False)
        return await deciding, timer.reserve[Player.S]

    result, reserve = asyncio.run(asyncio.wait_for(play(), timeout=5))
    assert result == "chosen"
    # only the 0.05s before the pause came off, and from the allowance
    assert reserve == 0.2
    clocks = [e for e in seats[Player.S].sent if e["type"] == OutEventType.CLOCK]
    assert any(e["paused"] for e in clocks)


def test_a_pause_holds_the_choice_without_a_clock():
    seats = {player: SilentSeat() for player in Player}

    async def play():
        pause = clock.Pause()
        assert clock.start_clock("unlimited", seats, pause) is None
        pause.set(Player.S, True)
        pause.set(Player.N, True)

        async def bot():
            return "move"

        deciding = asyncio.create_task(clock.decide(Player.N, True, bot(), list))
        await asyncio.sleep(0.05)
        # one player resuming isn't enough while the other still has it paused
        pause.set(Player.S, False)
        await asyncio.sleep(0.05)
        assert not deciding.done()
        pause.set(Player.N, False)
        return await deciding

    assert asyncio.run(asyncio.wait_for(play(), timeout=5)) == "move"
