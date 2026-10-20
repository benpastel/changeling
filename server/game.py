from dataclasses import dataclass, field
from typing import Optional, cast
from random import shuffle
import asyncio
import random

from server.agents import Agent, Human
from server.actions import (
    valid_targets,
    impacts,
    take_action,
    reflect_action,
    path,
)
from server.state import new_state, State, LogKind, LogEvent
from server.constants import (
    Player,
    Square,
    GameResult,
    Action,
    Tile,
    OtherAction,
    Response,
    ActionAndTarget,
    Claim,
    other_player,
)
from server.choices import send_prompt, send_waiting
from server.clock import start_clock, decide
from server.notify import (
    broadcast_state_changed,
    notify_selection_changed,
    broadcast_selection_changed,
    clear_selection,
    broadcast_game_over,
)


async def _resolve_bonus(
    state: State,
    players: dict[Player, Agent],
) -> None:
    """Give a player bonus for starting their turn on the bonus square"""
    player = state.maybe_player_at(state.bonus_position)
    if state.current_player != player:
        # current player does not get the bonus
        return

    revealed = 0
    for _ in range(state.bonus_reveal):
        revealed += state.reveal_unused()

    state.log(LogKind.BONUS, player, coins={player: state.bonus_amount}, count=revealed)
    state.coins[player] += state.bonus_amount
    await broadcast_state_changed(state, players)


async def _move_x2(
    square: Square,
    state: State,
    players: dict[Player, Agent],
) -> None:
    """Allow the player to move the x2 highlight."""
    player = state.player_at(square)
    await send_waiting(
        "Moving the ×2…",
        players[other_player(player)].seat,
    )
    choices: list[Action] = [t for t in Tile if t != state.x2_tile and t != Tile.HIDDEN]
    agent = players[player]
    if isinstance(agent, Human):
        choice = await decide(
            player,
            False,
            agent.choose_action_or_square(
                choices,
                [],
                "Move the ×2 to a different action.",
                true_action_hint=None,
            ),
            lambda: random.choice(choices),
        )
    else:
        choice = random.choice(choices)
    assert isinstance(choice, Tile)
    state.x2_tile = choice
    state.log(LogKind.X2, player, choice)

    await broadcast_state_changed(state, players)


async def _resolve_exchange(
    square: Square,
    state: State,
    players: dict[Player, Agent],
) -> None:
    """Allow a player to exchange with a exchange square"""
    player = state.player_at(square)
    exchange_index = state.exchange_positions.index(square)
    tile_on_board_index = state.positions[player].index(square)

    # player can now see the exchange position
    state.exchange_tiles_revealed[player][exchange_index] = True

    await broadcast_state_changed(state, players)
    await send_waiting(
        "Looking at the exchange…",
        players[other_player(player)].seat,
    )

    # if they could, other player can no longer see the exchange position or tile
    # because it may have change
    state.exchange_tiles_revealed[other_player(player)][exchange_index] = False
    state.tiles_on_board_revealed[player][tile_on_board_index] = False

    old_tile = state.tile_at(square)
    exchange_choices = state.exchange_tiles[exchange_index] + [old_tile]
    # out of time, they keep their tile
    choice = await decide(
        player,
        False,
        players[player].choose_exchange(
            exchange_choices,
            "Exchange tiles, or keep your current tile.",
        ),
        lambda: old_tile,
    )

    if choice != old_tile:
        # they swapped with a exchange tile
        state.tiles_on_board[player][tile_on_board_index] = choice
        state.exchange_tiles[exchange_index].remove(choice)
        state.exchange_tiles[exchange_index].append(old_tile)

        # shuffle to hide which tile they placed
        shuffle(state.exchange_tiles[exchange_index])

    state.log(LogKind.EXCHANGE, player, piece=state.piece_at(square))


async def _resolve_smite(
    state: State,
    player: Player,
    players: dict[Player, Agent],
    target: Square,
) -> None:
    state.coins[player] -= state.smite_cost
    state.log(LogKind.SMITE, player, coins={player: -state.smite_cost})

    await _lose_tile(target, state, players)
    await clear_selection(players)


async def _check_special_square(
    end_square: Square, state: State, players: dict[Player, Agent]
) -> None:
    """
    One of the players moved onto end_square, either directly or as side effect of an action;
    If it's a special square, resolve it.
    """
    if state.x2_tile is not None and end_square == state.bonus_position:
        await _move_x2(end_square, state, players)

    if end_square in state.exchange_positions:
        await _resolve_exchange(end_square, state, players)


async def _check_web(
    start: Square, target: Square, state: State, moving_player: Player
) -> None:
    """
    If the player moved onto an enemy web, they'll skip their next turn.  Doesn't stack.
    """
    already_skipping = state.skip_next_turn[moving_player]

    enemy_webs = state.webs[other_player(moving_player)]

    # if any of the squares on the path are enemy webs, the player skips their next turn
    # also clears any webs they stepped on
    for square in path(start, target):
        if square in enemy_webs:
            state.skip_next_turn[moving_player] = True
            enemy_webs.remove(square)

    if state.skip_next_turn[moving_player] and not already_skipping:
        state.log(LogKind.WEB, moving_player)


async def _resolve_action(
    start: Square,
    action: Action,
    target: Square,
    state: State,
    players: dict[Player, Agent],
    logged: LogEvent,
    reflect: bool = False,
) -> None:
    """
    Resolve the action, recording its coin changes on `logged`, the log event of the
    claim, reflect, or move that caused it.
    """
    repeats = 2 if state.x2_tile == action else 1
    before = _squares_by_piece(state)

    # `hits` is a possibly-empty list of tiles hit by the action
    coins_before = dict(state.coins)
    if reflect:
        hits = reflect_action(start, action, target, state)
    else:
        hits = take_action(start, action, target, state)
    logged.coins = {
        player: state.coins[player] - coins_before[player]
        for player in Player
        if state.coins[player] != coins_before[player]
    }
    # every tile that moved, by moving, being pulled, or swapping, and maybe sliding on
    # along ice; tiles a ram knocks back are just shoved, and don't count
    moved = [
        (player, before[player][piece], square)
        for player, by_piece in _squares_by_piece(state).items()
        for piece, square in by_piece.items()
        if square != before[player][piece]
        and not (action == Tile.RAM and before[player][piece] != start)
    ]

    for _ in range(repeats):
        for hit in hits:
            await _lose_tile(hit, state, players)

        await clear_selection(players)

    # they may have moved onto a special square, or across a web
    for player, from_square, to_square in moved:
        await _check_special_square(to_square, state, players)
        await _check_web(from_square, to_square, state, moving_player=player)

    # spider goes again after exchange
    if action == Tile.SPIDER and any(
        to_square in state.exchange_positions for _, _, to_square in moved
    ):
        state.go_again = True


def _squares_by_piece(state: State) -> dict[Player, dict[int, Square]]:
    return {
        player: dict(zip(state.piece_ids[player], state.positions[player]))
        for player in Player
    }


def _random_move(state: State) -> tuple[Square, Action, Square]:
    """
    A ↕ move by one of the current player's tiles, at random: what they do if they run
    out of time.  There's always one (see test_actions).
    """
    moves = [
        (start, target)
        for start in state.positions[state.current_player]
        for target in valid_targets(start, state).get(OtherAction.MOVE, [])
    ]
    start, target = random.choice(moves)
    return start, OtherAction.MOVE, target


async def _select_action(
    state: State, players: dict[Player, Agent]
) -> tuple[Square, Action, Square]:
    """
    Prompt the player to choose the action for their turn.

    Returns:
        - square of the tile that's taking the action
        - the action
        - target square of the action
    """
    await send_waiting(
        "Choosing an action…",
        players[state.other_player].seat,
    )
    current_agent = players[state.current_player]

    # a bot chooses its whole turn at once
    if not isinstance(current_agent, Human):
        start, action, target = await current_agent.choose_turn()
        assert target in valid_targets(start, state)[action]
        # show both players the proposed action
        await broadcast_selection_changed(
            state.current_player, start, action, target, players
        )
        return start, action, target

    possible_starts = state.positions[state.current_player]
    assert 1 <= len(possible_starts) <= 2
    if len(possible_starts) == 1:
        # only one choice
        start = possible_starts[0]
    else:
        choice = await current_agent.choose_action_or_square(
            [], possible_starts, "Select a tile.", true_action_hint=None
        )
        start = cast(Square, choice)

    # for humans, choose in a loop
    # to allow changing out choice of start square & action
    chosen_action: Optional[Action] = None
    while True:
        actions_and_targets = valid_targets(start, state)
        possible_actions = list(actions_and_targets.keys())
        possible_targets = actions_and_targets[chosen_action] if chosen_action else []

        # display the partial selection and valid actions/targets to the
        # current player
        await notify_selection_changed(
            state.current_player, start, chosen_action, None, current_agent.seat
        )

        if not chosen_action and len(possible_starts) == 1:
            possible_squares = []
            prompt = "Select an action."
        elif not chosen_action:
            possible_squares = possible_starts
            prompt = "Select an action, or a different tile."
        elif len(possible_starts) == 1:
            possible_squares = possible_targets
            prompt = "Select a target, or a different action."
        else:
            possible_squares = possible_starts + possible_targets
            prompt = "Select a target, or a different action or tile."

        # until an action is chosen, offer every action and target pair at once
        choice = await current_agent.choose_action_or_square(
            possible_actions,
            possible_squares,
            prompt,
            true_action_hint=None,
            targets=None if chosen_action else actions_and_targets,
            impacts=impacts(start, state),
        )
        if isinstance(choice, ActionAndTarget):
            # they chose an action and its target in one click
            await broadcast_selection_changed(
                state.current_player, start, choice.action, choice.target, players
            )
            return start, choice.action, choice.target
        elif choice in possible_targets:
            # they chose a target
            # we should now have all 3 selected
            assert chosen_action is not None
            target = cast(Square, choice)

            # show both players the proposed action
            await broadcast_selection_changed(
                state.current_player, start, chosen_action, target, players
            )
            return start, chosen_action, target
        elif choice in possible_actions:
            # they chose an action
            # go around again for the target or different action
            chosen_action = cast(Action, choice)
        else:
            # they chose a start square
            # go around again for the action or different start
            assert choice in possible_starts
            start = cast(Square, choice)
            chosen_action = None


async def _lose_tile(
    player_or_square: Player | Square,
    state: State,
    players: dict[Player, Agent],
) -> None:
    """
     - Prompt the player to choose a tile to lose, if applicable
     - choose the tile to replace it, if applicable
     - log the lost tile
     - update state

    If `player_or_square` is a square, the player must lose the tile on that square.
    (E.g. when that tile was hit by an attack.)

    If `player_or_square` is a player, the player chooses one tile on board to lose.
    (E.g. when the player lost a challenge.)
    """

    # select which tile on board is lost
    # in some cases the player gets a choice
    if isinstance(player_or_square, Square):
        # a specific square was lost to an attack, so they get no choice
        try:
            player = state.player_at(player_or_square)
        except ValueError:
            # if a double-attack killed the square and nothing replaced it,
            # it's possible the square is empty
            # in which case nothing happens
            return
        possible_squares = [player_or_square]
    else:
        # they lost a challenge, so they get a choice if they have multiple tiles
        assert player_or_square in Player
        player = player_or_square
        possible_squares = state.positions[player]

    if len(possible_squares) == 0:
        # they have no tiles to lose
        # i.e. their last tile was already killed by action
        return

    if len(possible_squares) > 1:
        # current player will need to choose a tile, so set a waiting prompt for opponent
        # and send any state updates so far to both players
        await broadcast_state_changed(state, players)
        await send_waiting(
            "Choosing a tile to lose…",
            players[other_player(player)].seat,
        )

    agent = players[player]

    if len(possible_squares) > 1:
        choice = await decide(
            player,
            False,
            agent.choose_square_or_hand(
                possible_squares,
                [],
                "Choose which tile to lose.",
            ),
            lambda: random.choice(possible_squares),
        )
        square = cast(Square, choice)
    else:
        square = possible_squares[0]

    # the tile dies as soon as it's known, so both players see it go before any
    # replacement is chosen
    tile = state.tile_at(square)
    position_index = state.positions[player].index(square)
    state.tiles_on_board[player].pop(position_index)
    state.positions[player].pop(position_index)
    state.tiles_on_board_revealed[player].pop(position_index)
    piece = state.piece_ids[player].pop(position_index)
    state.discard.append(tile)
    state.log(LogKind.LOSE, player, tile, piece=piece)
    state.score_point(other_player(player))

    hand_tiles = state.tiles_in_hand[player]
    replacement: Tile | None
    if len(hand_tiles) > 1:
        # the square waits, empty, while they choose which tile fills it
        state.vacant = {player: square}
        await clear_selection(players)
        await broadcast_state_changed(state, players)
        await send_waiting(
            "Choosing a replacement…",
            players[other_player(player)].seat,
        )
        choice = await decide(
            player,
            False,
            agent.choose_square_or_hand(
                possible_squares=[],
                possible_hand_tiles=hand_tiles,
                prompt="Choose the replacement tile from your hand.",
            ),
            lambda: random.choice(hand_tiles),
        )
        replacement = cast(Tile, choice)
        state.vacant = {}
    elif hand_tiles:
        replacement = hand_tiles[0]
    else:
        replacement = None

    if replacement:
        state.tiles_in_hand[player].remove(replacement)
        state.tiles_on_board[player].append(replacement)
        state.positions[player].append(square)
        state.tiles_on_board_revealed[player].append(False)
        state.piece_ids[player].append(state.next_piece_id)
        state.next_piece_id += 1

    await clear_selection(players)
    await broadcast_state_changed(state, players)


async def _select_response(
    start: Square,
    action: Action,
    target: Square,
    state: State,
    players: dict[Player, Agent],
) -> Response | Tile:
    assert action in Tile

    player_at_target = state.maybe_player_at(target)

    possible_responses: list[Response | Tile] = [
        Response.ACCEPT,
        Response.CHALLENGE,
    ]
    if action == Tile.HOOK:
        # Tile.HOOK reflects Tile.HOOK
        possible_responses.append(Tile.HOOK)
    elif action == Tile.THIEF:
        # Tile.THIEF reflects Tile.THIEF
        possible_responses.append(Tile.THIEF)
    elif action == Tile.KNIVES:
        # Tile.KNIVES reflects Tile.KNIVES
        possible_responses.append(Tile.KNIVES)
    elif action == Tile.BACKSTABBER and player_at_target == state.other_player:
        # only the kill can be reflected; moving onto an empty square has no defender
        # Tile.BACKSTABBER reflects Tile.BACKSTABBER
        possible_responses.append(Tile.BACKSTABBER)
    elif action == Tile.FIREBALL and player_at_target == state.other_player:
        # Tile.FIREBALL reflects Tile.FIREBALL, but only if the direct target is an enemy
        possible_responses.append(Tile.FIREBALL)

    await send_waiting(
        "Deciding whether to challenge…", players[state.current_player].seat
    )

    # out of time, they accept: neither challenge nor reflect
    return await decide(
        state.other_player,
        False,
        players[state.other_player].choose_response(
            possible_responses,
            f"Opponent claimed {action}.  Choose your response.",
            Claim(start, action, target),
        ),
        lambda: Response.ACCEPT,
    )


async def _select_reflect_response(
    start: Square,
    action: Action,
    target: Square,
    state: State,
    players: dict[Player, Agent],
) -> Response:
    await send_waiting(
        "Deciding whether to challenge the reflect…",
        players[state.other_player].seat,
    )
    response = await decide(
        state.current_player,
        False,
        players[state.current_player].choose_response(
            [Response.ACCEPT, Response.CHALLENGE],
            f"Opponent reflected with {action}.  Choose your response.",
            Claim(start, action, target, reflected=True),
        ),
        lambda: Response.ACCEPT,
    )
    return cast(Response, response)


async def _select_smite_target(
    state: State, player: Player, players: dict[Player, Agent]
) -> Square:
    await send_waiting(
        "Choosing a tile to smite…",
        players[other_player(player)].seat,
    )
    agent = players[player]
    targets = state.positions[other_player(player)]
    if not isinstance(agent, Human):
        return await agent.choose_smite_target(targets)

    # a person picks the target from a smite drawn on each enemy tile
    smite = await agent.choose_action_or_square(
        [],
        [],
        "Select a tile to smite ⚡",
        true_action_hint=None,
        targets={OtherAction.SMITE: targets},
    )
    assert isinstance(smite, ActionAndTarget)
    return smite.target


async def _maybe_smite(state: State, players: dict[Player, Agent]) -> None:
    """
    Check if either player has enough coins to smite.
    If so, select a target and resolve the smite.
    """
    if state.game_result() != GameResult.ONGOING:
        # sometimes we hit enough coins to smite at the same time as the game ends, if e.g.
        # the opponent lost a challenge.
        # only smite if the game is still ongoing
        return

    # if the current player has enough coins to smite, select a target and resolve the smite
    if state.smite_cost <= state.coins[state.current_player]:
        # the current player must have just gained enough coins to smite
        await clear_selection(players)
        # make sure both players see the updated coin amount before selecting a target
        await broadcast_state_changed(state, players)

        target = await decide(
            state.current_player,
            False,
            _select_smite_target(state, state.current_player, players),
            lambda: random.choice(state.positions[other_player(state.current_player)]),
        )
        await _resolve_smite(state, state.current_player, players, target)

    if state.smite_cost <= state.coins[state.other_player]:
        # the other player must have just gained enough coins to smite
        await clear_selection(players)
        # make sure both players see the updated coin amount before selecting a target
        await broadcast_state_changed(state, players)

        target = await decide(
            state.other_player,
            False,
            _select_smite_target(state, state.other_player, players),
            lambda: random.choice(state.positions[other_player(state.other_player)]),
        )
        await _resolve_smite(state, state.other_player, players, target)


async def _play_one_turn(state: State, players: dict[Player, Agent]) -> None:
    """
    Play one turn, prompting both players for choices as needed.

    Updates `state` with the result of the turn. Doesn't transition to the next turn
    or display that state to the players.
    """

    state.new_log_turn(state.current_player)

    if state.skip_next_turn[state.current_player]:
        state.log(LogKind.SKIP, state.current_player)
        state.skip_next_turn[state.current_player] = False
        await broadcast_state_changed(state, players)
        return

    # maybe give a bonus to current player for starting on the bonus square
    # this only happens once, even if the current player goes again
    await _resolve_bonus(state, players)

    # the bonus may push the current player's coins above the smite cost
    await _maybe_smite(state, players)

    # spider on exchange may allow the current player to go again
    # in which case we repeat the whole turn, except for the bonus
    state.go_again = True
    while state.go_again:
        state.go_again = False

        # a smite may already have decided the game, leaving a player with no tiles to move
        if state.game_result() != GameResult.ONGOING:
            return

        # current player chooses their move, or moves at random if out of time
        start, action, target = await decide(
            state.current_player,
            True,
            _select_action(state, players),
            lambda: _random_move(state),
        )
        if not action in Tile:
            assert action in OtherAction
            # the player didn't claim a tile
            # i.e. they moved or smited
            # so no possibility of challenge
            moved = state.log(LogKind.MOVE, state.current_player, action)
            await _resolve_action(start, action, target, state, players, moved)

            # the move may push the current player's coins up to the smite cost
            await _maybe_smite(state, players)
            continue

        # show the claim in the log while the opponent responds
        claim = state.log(
            LogKind.CLAIM, state.current_player, action, piece=state.piece_at(start)
        )
        await _show_log_keeping_selection(state, players, start, action, target)

        # ask opponent to accept, challenge, or reflect as appropriate
        response = await _select_response(start, action, target, state, players)

        if response == Response.ACCEPT:
            # other player allows the action to proceed
            await _resolve_action(start, action, target, state, players, claim)

        elif response == Response.CHALLENGE:
            state.log(LogKind.CHALLENGE, state.other_player)
            state.reveal_at(start)
            start_tile = state.tile_at(start)
            state.log(
                LogKind.REVEAL,
                state.current_player,
                start_tile,
                piece=state.piece_at(start),
            )
            if action == start_tile:
                # challenge fails
                # original action succeeds
                await _resolve_action(start, action, target, state, players, claim)
                await _lose_tile(state.other_player, state, players)
            else:
                # challenge succeeds
                # original action fails
                claim.cancelled = True
                await clear_selection(players)
                await _lose_tile(state.current_player, state, players)
        else:
            assert action == response
            # the response was to reflect
            # which the original player may challenge
            reflect = state.log(
                LogKind.REFLECT,
                state.other_player,
                response,
                piece=state.piece_at(target),
            )
            await _show_log_keeping_selection(
                state, players, start, action, target, reflect=response
            )
            reflect_response = await _select_reflect_response(
                start, action, target, state, players
            )
            target_tile = state.tile_at(target)

            if reflect_response == Response.ACCEPT:
                # reflect succeeds
                # original action fails
                claim.cancelled = True
                await clear_selection(players)
                await _resolve_action(
                    start, action, target, state, players, reflect, reflect=True
                )
            elif target_tile == response:
                # challenge fails
                # reflect succeeds
                # original action fails
                state.log(LogKind.CHALLENGE, state.current_player)
                state.reveal_at(target)
                state.log(
                    LogKind.REVEAL,
                    state.other_player,
                    target_tile,
                    piece=state.piece_at(target),
                )
                claim.cancelled = True
                await clear_selection(players)
                await _resolve_action(
                    start, action, target, state, players, reflect, reflect=True
                )
                await _lose_tile(state.current_player, state, players)
            else:
                state.log(LogKind.CHALLENGE, state.current_player)
                state.reveal_at(target)
                state.log(
                    LogKind.REVEAL,
                    state.other_player,
                    target_tile,
                    piece=state.piece_at(target),
                )
                # challenge succeeds
                # reflect fails
                # original action succeeds
                reflect.cancelled = True
                await _resolve_action(start, action, target, state, players, claim)
                await _lose_tile(state.other_player, state, players)

        # the action may push the current player's coins above the smite cost
        # or the opponent's, if an action was reflected
        await _maybe_smite(state, players)

        if state.go_again:
            state.log(LogKind.AGAIN, state.current_player)

        await broadcast_state_changed(state, players)


async def _show_log_keeping_selection(
    state: State,
    players: dict[Player, Agent],
    start: Square,
    action: Action,
    target: Square,
    reflect: Optional[Tile] = None,
) -> None:
    """
    Show both players the state (for the latest log), then the selection again, since
    redrawing the state redraws the action panel and loses the chosen action.
    """
    await broadcast_state_changed(state, players)
    await broadcast_selection_changed(
        state.current_player, start, action, target, players, reflect
    )


def _log_game_over(state: State) -> None:
    state.new_log_turn(None)
    result = state.game_result()
    if result == GameResult.NORTH_WINS:
        state.log(LogKind.WIN, Player.N)
    elif result == GameResult.SOUTH_WINS:
        state.log(LogKind.WIN, Player.S)
    else:
        state.log(LogKind.DRAW)


async def play_one_game(
    match_score: dict[Player, int],
    players: dict[Player, Agent],
    tiles: list[Tile] | None,
    first_player: Player,
    names: dict[Player, str],
    time_mode: str,
) -> tuple[dict[Player, int], GameResult]:
    """
    Play one game between the seated players.

    `tiles` is the set of tiles in use, or None to randomize it.  `time_mode` is one of
    clock.TIME_MODES.

    Returns the game score and result.
    """
    # initialize a new game
    state = new_state(match_score, tiles, first_player, names)
    # a bot follows the game through its own view of this state
    for player, agent in players.items():
        if not isinstance(agent, Human):
            agent.start_game(state, player)
    await broadcast_state_changed(state, players)
    clock = start_clock(
        time_mode, {player: agent.seat for player, agent in players.items()}
    )
    if clock is not None:
        await clock.send(None, 0)

    while state.game_result() == GameResult.ONGOING:
        state.check_consistency()

        await _play_one_turn(state, players)

        state.next_turn()

        await broadcast_state_changed(state, players)

    _log_game_over(state)
    # the game is over, so every tile is turned face up
    state.revealed_all = True
    await broadcast_state_changed(state, players)
    return state.game_score, state.game_result()


@dataclass
class Tally:
    """
    How a pair of players has done at a table: the games each has won and the points
    (kills) each has scored, over every game they've played there.  It outlives a match,
    which ends when they go back to the table, so it also says who moves first next.
    """

    wins: dict[Player, int] = field(default_factory=lambda: {p: 0 for p in Player})
    points: dict[Player, int] = field(default_factory=lambda: {p: 0 for p in Player})
    # south moves first in the first game, then the first move alternates
    first_player: Player = Player.S


async def play_one_match(
    players: dict[Player, Agent],
    tiles: list[Tile] | None,
    names: dict[Player, str],
    time_mode: str,
    tally: Tally,
) -> None:
    """
    Play games in a loop, adding each to `tally` and showing both players how it went,
    until either goes back to the table.
    """
    print(f"New match with {names}")
    while True:
        game_score, result = await play_one_game(
            tally.points.copy(), players, tiles, tally.first_player, names, time_mode
        )
        winner = {GameResult.NORTH_WINS: Player.N, GameResult.SOUTH_WINS: Player.S}.get(
            result
        )
        if winner is not None:
            tally.wins[winner] += 1
        for player, points in game_score.items():
            tally.points[player] += points
        tally.first_player = other_player(tally.first_player)

        # nothing more is asked of either player; then time to see every tile turn
        # over before the result covers the board
        for agent in players.values():
            await send_prompt("", agent.seat)
        await asyncio.sleep(1.5)

        play_on = await broadcast_game_over(
            players,
            {
                "winner": winner,
                "names": names,
                "game": game_score,
                "wins": tally.wins,
                "points": tally.points,
            },
        )
        if not play_on:
            return
