import random

from server.actions import impacts, take_action
from server.constants import OtherAction, Player, Square, Tile
from server.state import new_state


def _state():
    random.seed(0)
    state = new_state(
        {p: 0 for p in Player},
        [Tile.RAM, Tile.GRENADES, Tile.FIREBALL, Tile.HOOK, Tile.KNIVES],
        Player.N,
        {p: p.value for p in Player},
    )
    state.coins = {Player.N: 5, Player.S: 5}
    return state


def test_a_ram_impact_is_what_the_ram_then_does():
    state = _state()
    # the ram goes down to (2, 1); one enemy can be knocked to (4, 1), and the
    # other is pinned against the edge
    state.positions = {
        Player.N: [Square(1, 1), Square(0, 4)],
        Player.S: [Square(3, 1), Square(2, 0)],
    }
    impact = impacts(Square(1, 1), state)[Tile.RAM][Square(2, 1)]
    assert sorted(impact.moved) == [
        (Square(1, 1), Square(2, 1)),
        (Square(3, 1), Square(4, 1)),
    ]
    assert impact.killed == [Square(2, 0)]
    assert take_action(Square(1, 1), Tile.RAM, Square(2, 1), state) == impact.killed
    assert Square(4, 1) in state.positions[Player.S]


def test_a_grenade_impact_covers_three_by_three_and_kills_inside_it():
    state = _state()
    state.positions = {
        Player.N: [Square(0, 2), Square(0, 4)],
        Player.S: [Square(3, 2), Square(4, 4)],
    }
    impact = impacts(Square(0, 2), state)[Tile.GRENADES][Square(2, 2)]
    assert len(impact.area) == 9
    assert impact.killed == [Square(3, 2)]
    assert impact.moved == []


def test_working_out_impacts_leaves_the_game_alone():
    state = _state()
    state.positions = {
        Player.N: [Square(1, 1), Square(0, 4)],
        Player.S: [Square(3, 1), Square(2, 0)],
    }
    before = state.model_dump()
    found = impacts(Square(1, 1), state)
    assert OtherAction.MOVE in found
    assert state.model_dump() == before
