from dataclasses import dataclass
from typing import Optional

from server.state import State
from server.constants import (
    Square,
    Action,
    OtherAction,
    Tile,
    ROWS,
    COLUMNS,
    Player,
)
from server.config import NEGATIVE_COINS_OK


"""Money gains & costs"""
COIN_GAIN = {
    OtherAction.MOVE: 1,
    Tile.BIRD: 2,
    Tile.FLOWER: 3,
    Tile.HARVESTER: 4,
    Tile.BACKSTABBER: 2,
    Tile.SPIDER: 0,
}
SMITE_COST = 7
GRENADES_COST = 3
FIREBALL_COST = 3
KNIVES_RANGE_1_COST = 1
KNIVES_RANGE_2_COST = 5
GRAPPLE_STEAL_AMOUNT = 2
THIEF_STEAL_AMOUNT = 4
BACKSTAB_COST = 3
RAM_COST = 3
ICE_MAGE_COST = 3
WEB_STEAL_AMOUNT = 3


def path(start: Square, target: Square) -> list[Square]:
    """
    Return a list of squares from start to target
        excludes start
        includes target (if different from start)
    """
    # step towards the target, updating start until we reach the target
    # the direction is recomputed each step, so a target off the straight and diagonal
    # lines (e.g. a knight move) is reached by going diagonally, then straight
    path = []
    while start != target:
        row_change = (target.row > start.row) - (target.row < start.row)
        col_change = (target.col > start.col) - (target.col < start.col)
        start = Square(start.row + row_change, start.col + col_change)
        path.append(start)
    return path


def _all_distances(
    start: Square,
    obstructions: list[Square],
    rows: int = ROWS,
    cols: int = COLUMNS,
) -> dict[Square, int]:
    """
    Return the distance from the start to all squares, with routes:
        - allowed to end on an obstruction
        - not allowed to pass through an obstruction as an intermediate step
    """
    assert start not in obstructions
    assert 0 <= start.row < rows and 0 <= start.col < cols
    assert all(0 <= s.row < rows and 0 <= s.col < cols for s in obstructions)

    explored: dict[Square, int] = {}

    to_explore = [start]
    to_explore_dists = [0]

    while to_explore:
        s = to_explore.pop(0)
        dist = to_explore_dists.pop(0)
        if s in explored:
            continue

        explored[s] = dist

        if s in obstructions:
            continue

        for r, c in [
            (s.row - 1, s.col - 1),
            (s.row - 1, s.col + 0),
            (s.row - 1, s.col + 1),
            (s.row + 0, s.col - 1),
            (s.row + 0, s.col + 1),
            (s.row + 1, s.col - 1),
            (s.row + 1, s.col + 0),
            (s.row + 1, s.col + 1),
        ]:
            if 0 <= r < rows and 0 <= c < cols and Square(row=r, col=c) not in explored:
                to_explore.append(Square(row=r, col=c))
                to_explore_dists.append(dist + 1)
    return explored


def _manhattan_dist(s1: Square, s2: Square) -> int:
    return abs(s1.row - s2.row) + abs(s1.col - s2.col)


def grapple_end_square(
    start: Square, target: Square, obstructions: list[Square]
) -> Optional[Square]:
    """
    If the grapple is valid, return the square the enemy is pulled to.
    Otherwise return None.

    A grapple is valid if the target is a Queen move away (straight line or diagonal)
    and the enemy is in line of sight.

    The end square is the square adjacent to `start` which is nearest to `target` -
    i.e. the first square along the line of sight.
    """
    row_diff = target.row - start.row
    col_diff = target.col - start.col

    if not (
        row_diff == 0
        and col_diff != 0
        or row_diff != 0
        and col_diff == 0
        or abs(row_diff) == abs(col_diff)
    ):
        # not in a straight line / diagonal
        return None

    # which direction is a single step from start towards target?
    row_step = row_diff // abs(row_diff) if row_diff != 0 else 0
    col_step = col_diff // abs(col_diff) if col_diff != 0 else 0
    assert row_step != 0 or col_step != 0

    end_square = Square(row=start.row + row_step, col=start.col + col_step)

    # walk through the path and make sure no obstructions
    current_square = start
    while True:
        next_square = Square(
            row=current_square.row + row_step, col=current_square.col + col_step
        )
        # should never walk off board without hitting target
        assert 0 <= next_square.row < ROWS
        assert 0 <= next_square.col < COLUMNS

        if next_square == target:
            # this is the final square before target
            return end_square

        if next_square in obstructions:
            # we hit an obstruction first; this is not a legal move
            return None

        current_square = next_square


def _explosion_hits(center: Square, positions: list[Square]) -> list[Square]:
    """
    Return a possibly-empty list of tile positions hit by a 3x3 explosion centered on `center`.
    """
    return [
        hit
        for hit in positions
        if abs(center.row - hit.row) <= 1 and abs(center.col - hit.col) <= 1
    ]


def _midpoint(x: Square, y: Square) -> Square:
    new_row = (x.row + y.row) // 2
    new_col = (x.col + y.col) // 2
    return Square(new_row, new_col)


def _grenade_targets(
    start: Square, all_positions: list[Square], enemy_positions: list[Square]
) -> list[Square]:
    """
    Return a possibly-empty list of valid squares to target a grenade.

    Grenades can be thrown exactly 2 squares in a cardinal direction onto an empty square.
    They respect LOS (i.e. they cannot go over obstructions).

    For now we restrict to squares that hit at least one enemy to reduce misclicks.
    """
    assert len(enemy_positions) > 0
    assert all(e in all_positions for e in enemy_positions)

    # start with the empty squares at range
    potential_targets = [
        t
        for t in [
            Square(start.row + 2, start.col),
            Square(start.row - 2, start.col),
            Square(start.row, start.col + 2),
            Square(start.row, start.col - 2),
        ]
        if t.on_board()
        and not t in all_positions
        and not _midpoint(start, t) in all_positions
    ]

    # filter to ones that hit at least one enemy
    return [
        target
        for target in potential_targets
        if any(hit in enemy_positions for hit in _explosion_hits(target, all_positions))
    ]


def _fireball_targets(
    start: Square, obstructions: list[Square], enemies_and_webs: list[Square]
) -> list[Square]:
    """
    Return a possibly-empty list of valid squares to target a fireball.

    Fireballs travel diagonally in a straight line until they hit a tile, a web belonging to either player,
    or right before the edge of the board.  They explode on impact and destroy any tiles or webs in a 3x3 area
    centered on the impact.

    For now we restrict to squares that hit at least one enemy or web to reduce misclicks.
    """
    assert len(enemies_and_webs) > 0
    assert all(t in obstructions for t in enemies_and_webs)
    if start in obstructions:
        obstructions.remove(start)

    # start by finding the impact square in each diagonal direction
    impact_squares = []
    for row_step, col_step in [(1, 1), (1, -1), (-1, 1), (-1, -1)]:
        t = start
        next_t = Square(t.row + row_step, t.col + col_step)
        # stop if this square is an obstruction, or the next square is off the board
        while not t in obstructions and next_t.on_board():
            t = next_t
            next_t = Square(t.row + row_step, t.col + col_step)
        impact_squares.append(t)

    # filter to squares that hit at least one enemy or web
    return [
        t
        for t in impact_squares
        if any(hit in enemies_and_webs for hit in _explosion_hits(t, obstructions))
    ]


def valid_targets(start: Square, state: State) -> dict[Action, list[Square]]:
    """
    What are the valid actions for the current player from the start square,
    and what squares are those actions allowed to target?

    The square lists will be non-empty; if an action has no valid target, then
    it's not currently a valid action.
    """

    # all other tiles are obstructions that block line of sight
    obstructions = [s for s in state.all_positions() if s != start]
    distances = _all_distances(start, obstructions)

    coins = state.coins[state.current_player]

    enemy_positions = state.positions[state.other_player]

    empty_targets = {s: dist for s, dist in distances.items() if s not in obstructions}
    enemy_targets = {s: dist for s, dist in distances.items() if s in enemy_positions}

    # there must be enemies or the game would have ended
    assert len(enemy_targets) > 0

    # these actions cost no coins
    # and move to any empty square at some distance
    #
    # here we'll allow empty lists when there is no valid target square;
    # we'll drop those keys at the end
    flower_range = 2 if state.x2_tile == Tile.FLOWER else 1
    bird_range = 4 if state.x2_tile == Tile.BIRD else 2
    backstab_move_range = 4 if state.x2_tile == Tile.BACKSTABBER else 2
    ram_range = 2 if state.x2_tile == Tile.RAM else 1

    # TODO: manhattan distance should probably respect obstructions too
    bird_targets = [
        s
        for s, _ in empty_targets.items()
        if 1 <= _manhattan_dist(start, s) <= bird_range
    ]
    spider_targets = bird_targets
    if coins >= RAM_COST:
        # to reduce misclicks, only allow ram moves that knockback an enemy
        def _hits_any_enemy(s: Square) -> bool:
            _, pushed, killed = _ram_outcome(start, s, state)
            hits = [knocked for knocked, _ in pushed] + killed
            return len(set(hits) & set(enemy_positions)) > 0

        ram_targets = [
            s
            for s, _ in empty_targets.items()
            if 1 <= _manhattan_dist(start, s) <= ram_range and _hits_any_enemy(s)
        ]
    else:
        ram_targets = []
    # will append backstab enemy targets later
    backstab_targets = [
        s
        for s, _ in empty_targets.items()
        if 1 <= _manhattan_dist(start, s) <= backstab_move_range
    ]

    actions: dict[Action, list[Square]] = {
        OtherAction.MOVE: [s for s, dist in empty_targets.items() if dist == 1],
        Tile.FLOWER: [s for s, dist in empty_targets.items() if dist <= flower_range],
        Tile.BIRD: bird_targets,
        Tile.RAM: ram_targets,
        Tile.BACKSTABBER: backstab_targets,
        Tile.SPIDER: spider_targets,
    }

    # harvester costs no coins, and moves forward one square to an empty square.
    # forward is increasing rows for Player.N, and decreasing rows for Player.S
    forward = (
        Square(start.row + 1, start.col)
        if state.current_player == Player.N
        else Square(start.row - 1, start.col)
    )
    actions[Tile.HARVESTER] = [forward] if forward in empty_targets else []

    # the ice mage freezes the ring around itself, so it targets its own square
    if coins >= ICE_MAGE_COST:
        actions[Tile.ICE_MAGE] = [start]

    # see `grapple_end_square` for the definition of valid grapple targets
    actions[Tile.HOOK] = [
        s for s in enemy_targets if grapple_end_square(start, s, obstructions)
    ]
    actions[Tile.THIEF] = [s for s, dist in enemy_targets.items() if dist == 1]

    if coins >= KNIVES_RANGE_2_COST:
        actions[Tile.KNIVES] = [
            s for s in enemy_targets if 1 <= _manhattan_dist(start, s) <= 2
        ]
    elif coins >= KNIVES_RANGE_1_COST:
        actions[Tile.KNIVES] = [
            s for s in enemy_targets if 1 == _manhattan_dist(start, s)
        ]

    if coins >= GRENADES_COST:
        # see `_grenade_targets` for the definition of valid grenade targets
        actions[Tile.GRENADES] = _grenade_targets(start, obstructions, enemy_positions)

    if coins >= BACKSTAB_COST:
        # backstabber kills any enemy behind the start square
        # "behind" for Player.N is lower rows, and for Player.S is higher rows
        actions[Tile.BACKSTABBER] += [
            s
            for s in enemy_targets
            if (state.current_player == Player.N and s.row < start.row)
            or (state.current_player == Player.S and s.row > start.row)
        ]

    if coins >= FIREBALL_COST:
        enemies_and_webs = enemy_positions + state.all_webs()
        fireball_obstructions = obstructions + state.all_webs()
        actions[Tile.FIREBALL] = _fireball_targets(
            start, fireball_obstructions, enemies_and_webs
        )

    # drop actions with no valid targets
    ok_actions = {a: targets for a, targets in actions.items() if len(targets) > 0}

    # drop actions for tiles that are not in this game
    return {
        a: targets
        for a, targets in ok_actions.items()
        if a in state.tiles_in_game or a in OtherAction
    }


def _ram_outcome(
    start: Square, target: Square, state: State
) -> tuple[Square, list[tuple[Square, Square]], list[Square]]:
    """
    Where a ram from start to target would end up (it may slide on ice), where it
    would knock each neighbouring tile (which may slide too), and which tiles it would
    kill instead, for having nowhere to go.
    """
    # the ram has left its start for the target, and slides on from there
    occupied = [s for s in state.all_positions() if s != start]
    end = slide(target, _step(start, target), state.ice, occupied)
    occupied.append(end)
    distances = _all_distances(end, [s for s in occupied if s != end])
    pushed = []
    killed = []
    for knocked in [s for s, d in distances.items() if d == 1 and s in occupied]:
        # each knocked tile goes directly away from the ram; if that's obstructed, it
        # dies
        step = _step(end, knocked)
        knocked_to = Square(knocked.row + step[0], knocked.col + step[1])
        if knocked_to.on_board() and knocked_to not in occupied:
            occupied.remove(knocked)
            knocked_to = slide(knocked_to, step, state.ice, occupied)
            occupied.append(knocked_to)
            pushed.append((knocked, knocked_to))
        else:
            killed.append(knocked)
    return end, pushed, killed


def _take_ram_action(start: Square, target: Square, state: State) -> list[Square]:
    """
    Makes a ram move, updating state, and returning any tiles killed.
    """
    player = state.current_player
    end, pushed, killed = _ram_outcome(start, target, state)

    # move to target square, or past it on ice
    start_index = state.positions[player].index(start)
    state.positions[player][start_index] = end

    # spend cost
    state.coins[player] -= RAM_COST

    # knockback any neighboring tiles
    for knocked_square, end_square in pushed:
        knocked_player = state.player_at(knocked_square)
        knocked_index = state.positions[knocked_player].index(knocked_square)
        state.positions[knocked_player][knocked_index] = end_square
    return killed


@dataclass
class Impact:
    """What an action on a square would do, if it went ahead."""

    # every square a blast or a freeze covers
    area: list[Square]
    # every tile that would die
    killed: list[Square]
    # every tile that would end up on another square (the actor too), and where
    moved: list[tuple[Square, Square]]


def impacts(start: Square, state: State) -> dict[Action, dict[Square, Impact]]:
    """The impact of everything the tile at start could do, by action and target."""
    before = {
        piece: square
        for player in Player
        for piece, square in zip(state.piece_ids[player], state.positions[player])
    }
    found: dict[Action, dict[Square, Impact]] = {}
    for action, targets in valid_targets(start, state).items():
        found[action] = {}
        for target in targets:
            sim = state.scratch()
            killed = take_action(start, action, target, sim)
            moved = [
                (before[piece], square)
                for player in Player
                for piece, square in zip(sim.piece_ids[player], sim.positions[player])
                if before[piece] != square
            ]
            if action in (Tile.FIREBALL, Tile.GRENADES):
                area = _around(target, 1)
            elif action == Tile.ICE_MAGE:
                area = ice_ring(start)
            else:
                area = []
            found[action][target] = Impact(area, killed, moved)
    return found


def _around(center: Square, distance: int) -> list[Square]:
    """Every square on the board within `distance` of center, straight or diagonal."""
    return [
        square
        for row in range(center.row - distance, center.row + distance + 1)
        for col in range(center.col - distance, center.col + distance + 1)
        if (square := Square(row, col)).on_board()
    ]


def ice_ring(center: Square) -> list[Square]:
    """The squares an ice mage freezes: the edge of the 5x5 square around it."""
    return [s for s in _around(center, 2) if s not in _around(center, 1)]


def _step(start: Square, target: Square) -> tuple[int, int]:
    """
    The last single step (straight or diagonal) of a move from start to target, the
    way a tile landing on ice keeps going; see `path`.
    """
    squares = [start] + path(start, target)
    if len(squares) < 2:
        return (0, 0)
    before, after = squares[-2], squares[-1]
    return (after.row - before.row, after.col - before.col)


def slide(
    square: Square, step: tuple[int, int], ice: list[Square], occupied: list[Square]
) -> Square:
    """
    Where a tile that has just moved onto `square`, going `step` at a time, comes to
    rest: on ice it keeps going, until it's off the ice or the next square is off the
    board or taken.
    """
    if step == (0, 0):
        return square
    while square in ice:
        after = Square(square.row + step[0], square.col + step[1])
        if not after.on_board() or after in occupied:
            break
        square = after
    return square


def _move(state: State, player: Player, start: Square, target: Square) -> Square:
    """Move the player's tile at start onto target, and on along any ice."""
    index = state.positions[player].index(start)
    state.positions[player][index] = target
    end = slide(target, _step(start, target), state.ice, state.all_positions())
    state.positions[player][index] = end
    return end


def _swap(state: State, start: Square, target: Square) -> None:
    """Swap the tiles at start and target, each sliding on along any ice."""
    start_player = state.player_at(start)
    target_player = state.player_at(target)
    start_index = state.positions[start_player].index(start)
    target_index = state.positions[target_player].index(target)
    state.positions[start_player][start_index] = target
    state.positions[target_player][target_index] = start
    state.positions[start_player][start_index] = slide(
        target, _step(start, target), state.ice, state.all_positions()
    )
    state.positions[target_player][target_index] = slide(
        start, _step(target, start), state.ice, state.all_positions()
    )


def take_action(
    start: Square, action: Action, target: Square, state: State
) -> list[Square]:
    """
    Updates the state with the result of the action.
    Assumes the action is valid.

    Returns a possibly-empty list of casualties (positions of tiles that got killed)
    """
    player = state.current_player
    enemy = state.other_player
    repeats = 2 if state.x2_tile == action else 1

    if action in (
        OtherAction.MOVE,
        Tile.FLOWER,
        Tile.BIRD,
        Tile.HARVESTER,
        Tile.SPIDER,
    ) or (action == Tile.BACKSTABBER and state.maybe_player_at(target) is None):
        # move to the target square, and on along any ice
        end = _move(state, player, start, target)

        # spider lays web on all traveled squares
        if action == Tile.SPIDER:
            for square in [start] + path(start, end):
                if square not in state.webs[player]:
                    state.webs[player].append(square)

        # gain coins
        state.coins[player] += COIN_GAIN[action] * repeats

        if action == Tile.BIRD:
            for repeat in range(repeats):
                # reveal 1 unused tile
                state.reveal_unused()

        # kill nobody
        return []

    if action == Tile.RAM:
        return _take_ram_action(start, target, state)

    if action == Tile.HOOK:
        # move target next to us
        end_square = grapple_end_square(start, target, obstructions=[])
        assert end_square
        _move(state, enemy, target, end_square)

        # steal
        if NEGATIVE_COINS_OK:
            steal_amount = GRAPPLE_STEAL_AMOUNT * repeats
        else:
            steal_amount = min(GRAPPLE_STEAL_AMOUNT * repeats, state.coins[enemy])
        state.coins[player] += steal_amount
        state.coins[enemy] -= steal_amount

        # kill noboby
        return []

    if action == Tile.THIEF:
        # swap places with target
        _swap(state, start, target)

        # steal
        if NEGATIVE_COINS_OK:
            steal_amount = THIEF_STEAL_AMOUNT * repeats
        else:
            steal_amount = min(THIEF_STEAL_AMOUNT * repeats, state.coins[enemy])
        state.coins[player] += steal_amount
        state.coins[enemy] -= steal_amount

        # kill noboby
        return []

    if action == Tile.GRENADES:
        # pay cost
        state.coins[player] -= GRENADES_COST

        # remove all webs hit by blast
        for web in _explosion_hits(target, state.webs[player]):
            state.webs[player].remove(web)
        for web in _explosion_hits(target, state.webs[enemy]):
            state.webs[enemy].remove(web)
        return _explosion_hits(target, state.all_positions())

    if action == Tile.FIREBALL:
        # pay cost
        state.coins[player] -= FIREBALL_COST

        # remove all webs hit by blast
        for web in _explosion_hits(target, state.webs[player]):
            state.webs[player].remove(web)
        for web in _explosion_hits(target, state.webs[enemy]):
            state.webs[enemy].remove(web)
        return _explosion_hits(target, state.all_positions())

    if action == Tile.ICE_MAGE:
        # pay cost
        state.coins[player] -= ICE_MAGE_COST

        # ice the ring, and kill everything on it, own tiles too
        ring = ice_ring(start)
        state.ice += [square for square in ring if square not in state.ice]
        return [square for square in state.all_positions() if square in ring]

    if action == Tile.KNIVES:
        # cost depends on distance to target
        dist = _manhattan_dist(start, target)

        if dist == 2:
            state.coins[player] -= KNIVES_RANGE_2_COST
        else:
            assert dist == 1
            state.coins[player] -= KNIVES_RANGE_1_COST

        # kill target
        return [target]

    if action == Tile.BACKSTABBER and state.maybe_player_at(target) is not None:
        # pay cost
        state.coins[player] -= BACKSTAB_COST

        # kill target
        return [target]

    assert False, f"unknown {action=}"


def reflect_action(
    start: Square, action: Action, target: Square, state: State
) -> list[Square]:
    """
    Updates the state with the result of the action reflected from target to start.
    Assumes the action is valid.

    Returns a possibly-empty list of casualties (positions of tiles that got killed)
    """
    player = state.current_player
    enemy = state.other_player
    repeats = 2 if state.x2_tile == action else 1

    if action == Tile.KNIVES or action == Tile.BACKSTABBER:
        # kill start @ no cost
        return [start]

    if action == Tile.HOOK:
        # move start next to target
        end_square = grapple_end_square(target, start, obstructions=[])
        assert end_square
        _move(state, player, start, end_square)

        # steal; same as original action with players swapped
        if NEGATIVE_COINS_OK:
            steal_amount = GRAPPLE_STEAL_AMOUNT * repeats
        else:
            steal_amount = min(GRAPPLE_STEAL_AMOUNT * repeats, state.coins[player])
        state.coins[enemy] += steal_amount
        state.coins[player] -= steal_amount

        # kill noboby
        return []

    if action == Tile.THIEF:
        # swap places with target; same as original action
        _swap(state, start, target)

        # steal; same as original action with players swapped
        if NEGATIVE_COINS_OK:
            steal_amount = THIEF_STEAL_AMOUNT * repeats
        else:
            steal_amount = min(THIEF_STEAL_AMOUNT * repeats, state.coins[player])
        state.coins[enemy] += steal_amount
        state.coins[player] -= steal_amount

        # kill noboby
        return []

    if action == Tile.FIREBALL:
        # explode at start
        return _explosion_hits(start, state.all_positions())

    assert False, f"unknown {action=}"


def _knockback_end_square(origin: Square, knocked: Square) -> Square:
    """
    Return the square that a tile would be knocked back to.

    Args:
        origin: Square doing the knocking
        knocked: Square being knocked back (must be distance 1 from origin)

    Returns:
        Square at distance 2 from origin in the same direction as knocked
    """
    # Get the direction vector from origin to knocked
    row_diff = knocked.row - origin.row
    col_diff = knocked.col - origin.col

    # Double it to get the end square
    return Square(row=origin.row + (row_diff * 2), col=origin.col + (col_diff * 2))
