import asyncio
import random

from server.actions import (
    SUNBEAM_COST,
    impacts,
    reflect_action,
    take_action,
    valid_targets,
)
from server.bots import Bot
from server.constants import Player, Square, Tile
from server.game import _resolve_action, _select_response
from server.state import LogKind, State, new_state

N, S = Player.N, Player.S


def _state(north: list[Square], south: list[Square]) -> State:
    random.seed(0)
    state = new_state(
        {p: 0 for p in Player},
        [Tile.SUNBEAM, Tile.KNIVES, Tile.HOOK, Tile.FIREBALL, Tile.BIRD],
        N,
        {p: p.value for p in Player},
    )
    state.positions = {N: north, S: south}
    state.piece_ids = {N: [0, 1][: len(north)], S: [2, 3][: len(south)]}
    state.tiles_on_board_revealed = {N: [False] * len(north), S: [False] * len(south)}
    state.coins = {N: 5, S: 5}
    return state


def _revealed(state: State, square: Square) -> bool:
    player = state.player_at(square)
    return state.tiles_on_board_revealed[player][state.positions[player].index(square)]


def test_a_sunbeam_aims_at_the_first_tile_straight_along_a_line_to_an_enemy():
    # up the column: an ally, then an enemy behind it; right along the row: an enemy;
    # diagonally: an enemy, which a sunbeam can't reach
    state = _state(
        [Square(4, 2), Square(2, 2)],
        [Square(0, 2), Square(4, 4)],
    )
    state.positions[S].append(Square(3, 3))
    state.piece_ids[S].append(4)
    state.tiles_on_board_revealed[S].append(False)
    assert sorted(valid_targets(Square(4, 2), state)[Tile.SUNBEAM]) == [
        Square(2, 2),
        Square(4, 4),
    ]


def test_a_sunbeam_needs_an_enemy_in_the_line_and_its_cost():
    state = _state([Square(4, 2), Square(2, 2)], [Square(0, 0)])
    assert Tile.SUNBEAM not in valid_targets(Square(4, 2), state)
    state = _state([Square(4, 2)], [Square(0, 2)])
    state.coins[N] = SUNBEAM_COST - 1
    assert Tile.SUNBEAM not in valid_targets(Square(4, 2), state)


def test_a_sunbeam_reveals_every_tile_to_the_edge_and_nothing_else():
    state = _state([Square(4, 2), Square(3, 2)], [Square(1, 2), Square(1, 1)])
    assert take_action(Square(4, 2), Tile.SUNBEAM, Square(3, 2), state) == []
    assert _revealed(state, Square(3, 2)) and _revealed(state, Square(1, 2))
    assert not _revealed(state, Square(4, 2)) and not _revealed(state, Square(1, 1))
    assert state.coins[N] == 5 - SUNBEAM_COST


def test_a_reflected_sunbeam_reveals_the_claimer_and_everything_behind_it_free():
    state = _state([Square(2, 2), Square(4, 2)], [Square(1, 2), Square(0, 2)])
    assert reflect_action(Square(2, 2), Tile.SUNBEAM, Square(1, 2), state) == []
    assert _revealed(state, Square(2, 2)) and _revealed(state, Square(4, 2))
    assert not _revealed(state, Square(1, 2)) and not _revealed(state, Square(0, 2))
    assert state.coins == {N: 5, S: 5}


def test_a_sunbeams_preview_lights_its_tile_to_the_edge():
    state = _state([Square(4, 2)], [Square(2, 2)])
    impact = impacts(Square(4, 2), state)[Tile.SUNBEAM][Square(2, 2)]
    assert impact.area == [
        Square(4, 2),
        Square(3, 2),
        Square(2, 2),
        Square(1, 2),
        Square(0, 2),
    ]
    assert impact.killed == [] and impact.moved == []


class _Answering(Bot):
    """Records what it was offered."""

    offered: list = []

    async def choose_response(self, possible_responses, prompt, claim):
        _Answering.offered = list(possible_responses)
        return possible_responses[0]


def _offered(state: State, target: Square) -> list:
    players = {p: _Answering("easy", delay=0) for p in Player}
    for player, bot in players.items():
        bot.start_game(state, player)
    asyncio.run(
        _select_response(Square(4, 2), Tile.SUNBEAM, target, state, dict(players))
    )
    return _Answering.offered


def test_only_an_enemy_first_in_the_beam_can_reflect_it():
    state = _state([Square(4, 2)], [Square(2, 2), Square(0, 2)])
    assert Tile.SUNBEAM in _offered(state, Square(2, 2))
    # an ally first in the beam: the enemy behind it is just caught in the light
    state = _state([Square(4, 2), Square(3, 2)], [Square(0, 2)])
    assert Tile.SUNBEAM not in _offered(state, Square(3, 2))


def test_what_a_sunbeam_shows_is_logged():
    state = _state([Square(4, 2), Square(3, 2)], [Square(1, 2), Square(0, 0)])
    players = {p: Bot("easy", delay=0) for p in Player}
    for player, bot in players.items():
        bot.start_game(state, player)
    state.new_log_turn(N)
    logged = state.log(LogKind.CLAIM, N, Tile.SUNBEAM)
    asyncio.run(
        _resolve_action(
            Square(4, 2), Tile.SUNBEAM, Square(3, 2), state, dict(players), logged
        )
    )
    lit = [e for e in state.public_log[-1].events if e.kind == LogKind.LIT]
    assert [(e.player, e.action) for e in lit] == [
        (N, state.tiles_on_board[N][1]),
        (S, state.tiles_on_board[S][0]),
    ]
