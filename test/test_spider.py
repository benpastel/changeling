import asyncio
import random

from server.actions import valid_targets
from server.bots import Bot
from server.constants import OtherAction, Player, Response, Square, Tile
from server.game import MOVES_PER_TURN, _play_one_turn, _resolve_action
from server.state import LogKind, State, new_state

N, S = Player.N, Player.S


def _state() -> State:
    random.seed(0)
    state = new_state(
        {p: 0 for p in Player},
        [Tile.SPIDER, Tile.KNIVES, Tile.HOOK, Tile.FIREBALL, Tile.BIRD],
        N,
        {p: p.value for p in Player},
    )
    state.positions = {N: [Square(2, 0), Square(0, 0)], S: [Square(4, 4), Square(4, 0)]}
    # keep the special squares out of the way
    state.exchange_positions = [Square(0, 3), Square(0, 4)]
    state.bonus_position = Square(0, 2)
    return state


class _Spider(Bot):
    """Claims a spider move whenever it can, and accepts every claim."""

    turns = 0

    async def choose_turn(self):
        _Spider.turns += 1
        state = self._state
        for start in state.positions[self.me]:
            targets = valid_targets(start, state).get(Tile.SPIDER)
            if targets:
                return start, Tile.SPIDER, targets[0]
        raise AssertionError("no spider move")

    async def choose_response(self, possible_responses, prompt, claim):
        return Response.ACCEPT


def _players(state: State) -> dict:
    players = {p: _Spider("easy", delay=0) for p in Player}
    for player, bot in players.items():
        bot.start_game(state, player)
    return dict(players)


def test_a_spider_goes_again_but_only_once():
    state = _state()
    _Spider.turns = 0
    asyncio.run(_play_one_turn(state, _players(state)))
    assert _Spider.turns == MOVES_PER_TURN == 2
    kinds = [e.kind for e in state.public_log[-1].events]
    assert kinds.count(LogKind.AGAIN) == 1


def test_a_web_holds_its_catch_until_their_lost_turn_then_goes():
    state = _state()
    state.webs[S] = [Square(2, 1), Square(3, 3)]
    piece = state.piece_at(Square(2, 0))
    state.new_log_turn(N)
    logged = state.log(LogKind.MOVE, N, OtherAction.MOVE)
    players = _players(state)
    asyncio.run(
        _resolve_action(
            Square(2, 0), OtherAction.MOVE, Square(2, 1), state, players, logged
        )
    )
    # caught, and the web stays to show it
    assert state.skip_next_turn[N]
    assert state.webs[S] == [Square(2, 1), Square(3, 3)]
    web = [e for e in state.public_log[-1].events if e.kind == LogKind.WEB]
    assert [e.piece for e in web] == [piece]

    # north's next turn is lost, naming the piece, and the web that caught it goes
    asyncio.run(_play_one_turn(state, players))
    skip = state.public_log[-1].events
    assert [(e.kind, e.piece) for e in skip] == [(LogKind.SKIP, piece)]
    assert state.webs[S] == [Square(3, 3)]
    assert state.caught[N] == [] and not state.skip_next_turn[N]
