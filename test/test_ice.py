import asyncio
import random

from server.actions import impacts, take_action, valid_targets
from server.bots import Bot
from server.constants import OtherAction, Player, Square, Tile
from server.game import _resolve_action
from server.state import LogKind, State, new_state

N, S = Player.N, Player.S


def _state(north: list[Square], south: list[Square], ice: list[Square]) -> State:
    random.seed(0)
    state = new_state(
        {p: 0 for p in Player},
        [Tile.FROST, Tile.RAM, Tile.THIEF, Tile.HOOK, Tile.BIRD],
        N,
        {p: p.value for p in Player},
    )
    state.positions = {N: north, S: south}
    state.piece_ids = {N: [0, 1][: len(north)], S: [2, 3][: len(south)]}
    state.ice = ice
    state.coins = {N: 5, S: 5}
    # keep the special squares out of the way
    state.exchange_positions = [Square(4, 3), Square(4, 4)]
    state.bonus_position = Square(4, 2)
    return state


def _row(row: int, *cols: int) -> list[Square]:
    return [Square(row, col) for col in cols]


# ------------------------------------------------------------------ sliding


def test_a_tile_slides_on_until_it_is_off_the_ice():
    state = _state([Square(2, 0)], [Square(0, 4)], ice=_row(2, 1, 2))
    take_action(Square(2, 0), OtherAction.MOVE, Square(2, 1), state)
    assert state.positions[N] == [Square(2, 3)]


def test_a_slide_stops_short_of_a_tile_without_harming_it():
    state = _state([Square(2, 0)], [Square(2, 3), Square(0, 4)], ice=_row(2, 1, 2))
    assert take_action(Square(2, 0), OtherAction.MOVE, Square(2, 1), state) == []
    assert state.positions[N] == [Square(2, 2)]
    assert state.positions[S] == [Square(2, 3), Square(0, 4)]


def test_a_slide_stops_at_the_edge_of_the_board():
    state = _state([Square(2, 1)], [Square(0, 0)], ice=_row(2, 2, 3, 4))
    take_action(Square(2, 1), OtherAction.MOVE, Square(2, 2), state)
    assert state.positions[N] == [Square(2, 4)]


def test_a_diagonal_move_slides_diagonally():
    state = _state([Square(0, 0)], [Square(0, 4)], ice=[Square(1, 1), Square(2, 2)])
    take_action(Square(0, 0), OtherAction.MOVE, Square(1, 1), state)
    assert state.positions[N] == [Square(3, 3)]


def test_a_bent_move_slides_the_way_its_last_step_went():
    # a bird from (0, 0) to (1, 2) goes diagonally to (1, 1), then right
    state = _state([Square(0, 0)], [Square(4, 0)], ice=[Square(1, 2)])
    take_action(Square(0, 0), Tile.BIRD, Square(1, 2), state)
    assert state.positions[N] == [Square(1, 3)]


def test_passing_over_ice_without_stopping_on_it_does_nothing():
    state = _state([Square(2, 0)], [Square(0, 4)], ice=[Square(2, 1)])
    take_action(Square(2, 0), Tile.BIRD, Square(2, 2), state)
    assert state.positions[N] == [Square(2, 2)]


def test_stepping_off_ice_does_nothing():
    state = _state([Square(2, 1)], [Square(0, 4)], ice=[Square(2, 1)])
    take_action(Square(2, 1), OtherAction.MOVE, Square(2, 2), state)
    assert state.positions[N] == [Square(2, 2)]


def test_a_ram_slides_then_knocks_back_from_where_it_stops():
    # the ram slides from (2, 1) to (2, 3), then knocks (1, 3) up onto (0, 3): iced,
    # but at the edge, so it stays
    state = _state(
        [Square(2, 0)],
        [Square(1, 3), Square(4, 0)],
        ice=_row(2, 1, 2) + [Square(0, 3)],
    )
    impact = impacts(Square(2, 0), state)[Tile.RAM][Square(2, 1)]
    assert take_action(Square(2, 0), Tile.RAM, Square(2, 1), state) == []
    assert state.positions[N] == [Square(2, 3)]
    assert state.positions[S] == [Square(0, 3), Square(4, 0)]
    assert sorted(impact.moved) == [
        (Square(1, 3), Square(0, 3)),
        (Square(2, 0), Square(2, 3)),
    ]


def test_a_tile_knocked_onto_ice_slides_on():
    # the ram goes right to (2, 1), knocking (2, 2) onto (2, 3), which slides to (2, 4)
    state = _state([Square(2, 0)], [Square(2, 2), Square(4, 0)], ice=[Square(2, 3)])
    take_action(Square(2, 0), Tile.RAM, Square(2, 1), state)
    assert state.positions[S] == [Square(2, 4), Square(4, 0)]


def test_a_thief_and_its_victim_each_slide_on_away_from_each_other():
    state = _state([Square(2, 1)], [Square(2, 2), Square(4, 4)], ice=_row(2, 1, 2, 3))
    take_action(Square(2, 1), Tile.THIEF, Square(2, 2), state)
    assert state.positions[N] == [Square(2, 4)]
    assert state.positions[S] == [Square(2, 0), Square(4, 4)]


def test_a_hooked_tile_on_ice_stops_against_the_hook():
    state = _state([Square(2, 0)], [Square(2, 4), Square(4, 4)], ice=_row(2, 1, 2, 3))
    take_action(Square(2, 0), Tile.HOOK, Square(2, 4), state)
    assert state.positions[S] == [Square(2, 1), Square(4, 4)]


# ------------------------------------------------------------------ frost


def test_frost_kills_and_ices_the_ring_around_it_own_tiles_too():
    state = _state(
        [Square(2, 2), Square(0, 0)],
        [Square(4, 3), Square(3, 3)],
        ice=[],
    )
    assert valid_targets(Square(2, 2), state)[Tile.FROST] == [Square(2, 2)]
    killed = take_action(Square(2, 2), Tile.FROST, Square(2, 2), state)
    # the corner and the far edge are in the ring; (3, 3) is too close
    assert sorted(killed) == [Square(0, 0), Square(4, 3)]
    assert len(state.ice) == 16
    assert Square(3, 3) not in state.ice and Square(2, 2) not in state.ice
    assert state.coins[N] == 2


def test_frost_by_the_edge_ices_only_what_is_on_the_board():
    state = _state([Square(0, 0)], [Square(4, 4)], ice=[Square(2, 2)])
    take_action(Square(0, 0), Tile.FROST, Square(0, 0), state)
    # (0..2, 2) and (2, 0..1); (2, 2) was iced already
    assert sorted(state.ice) == [
        Square(0, 2),
        Square(1, 2),
        Square(2, 0),
        Square(2, 1),
        Square(2, 2),
    ]


def test_frost_needs_its_cost():
    state = _state([Square(2, 2)], [Square(0, 0)], ice=[])
    state.coins[N] = 2
    assert Tile.FROST not in valid_targets(Square(2, 2), state)


def test_ice_is_public():
    state = _state([Square(2, 2)], [Square(0, 0)], ice=[Square(1, 1)])
    assert state.player_view(S).ice == [Square(1, 1)]


def test_blasts_melt_ice_without_being_stopped_by_it():
    state = _state([Square(0, 0)], [Square(3, 3)], ice=_row(1, 1) + _row(3, 2, 3, 4))
    state.tiles_in_game = [Tile.FIREBALL, *state.tiles_in_game[1:]]
    # the fireball flies over the ice at (1, 1) and hits (3, 3)
    assert Square(3, 3) in valid_targets(Square(0, 0), state)[Tile.FIREBALL]
    take_action(Square(0, 0), Tile.FIREBALL, Square(3, 3), state)
    assert state.ice == [Square(1, 1)]


# ------------------------------------------------------------------ in the game


def _resolve(state: State, start: Square, action, target: Square) -> None:
    players = {p: Bot("easy", delay=0) for p in Player}
    for player, bot in players.items():
        bot.start_game(state, player)
    state.new_log_turn(N)
    logged = state.log(LogKind.CLAIM, N, action)
    asyncio.run(_resolve_action(start, action, target, state, dict(players), logged))


def test_sliding_onto_an_exchange_offers_it():
    state = _state([Square(4, 0)], [Square(0, 4)], ice=[Square(4, 1), Square(4, 2)])
    _resolve(state, Square(4, 0), OtherAction.MOVE, Square(4, 1))
    assert state.positions[N] == [Square(4, 3)]
    kinds = [event.kind for event in state.public_log[-1].events]
    assert LogKind.EXCHANGE in kinds


def test_sliding_across_an_enemy_web_catches_you():
    state = _state([Square(2, 0)], [Square(0, 4)], ice=_row(2, 1, 2))
    state.webs[S] = [Square(2, 2)]
    _resolve(state, Square(2, 0), OtherAction.MOVE, Square(2, 1))
    assert state.positions[N] == [Square(2, 3)]
    assert state.skip_next_turn[N]


def test_a_spider_lays_webs_along_its_slide():
    state = _state([Square(2, 0)], [Square(0, 4)], ice=_row(2, 1, 2))
    state.tiles_in_game = [Tile.SPIDER, *state.tiles_in_game[1:]]
    take_action(Square(2, 0), Tile.SPIDER, Square(2, 1), state)
    assert state.webs[N] == _row(2, 0, 1, 2, 3)
