import asyncio
import random
from collections import Counter

import pytest

from server.bots import Bot, LEVELS, claims_since_exchange, lie_chance
from server.constants import (
    Claim,
    GameResult,
    Player,
    Response,
    Square,
    Tile,
)
from server.game import _resolve_action, play_one_game
from server.state import LogKind, State, new_state

# tiles with every kind of action between them, beyond the starter set
EVERYTHING = [Tile.TRICKSTER, Tile.SPIDER, Tile.RAM, Tile.THIEF, Tile.GRENADES]


def _play(north: str, south: str, tiles: list[Tile] | None, seed: int) -> State:
    random.seed(seed)
    bots = {
        Player.N: Bot(north, delay=0, rng=random.Random(seed)),
        Player.S: Bot(south, delay=0, rng=random.Random(seed + 1)),
    }
    asyncio.run(
        asyncio.wait_for(
            play_one_game(
                {p: 0 for p in Player},
                {p: b for p, b in bots.items()},
                tiles,
                Player.S,
                {p: p.value for p in Player},
                "unlimited",
            ),
            timeout=30,
        )
    )
    state = bots[Player.N]._state
    assert state is not None
    return state


@pytest.mark.parametrize("north", LEVELS)
@pytest.mark.parametrize("south", LEVELS)
def test_every_level_plays_games_to_the_end(north, south):
    # random tile sets, and one with tricksters, spiders, rams, thieves and grenades
    for seed, tiles in [(1, None), (2, None), (3, EVERYTHING)]:
        state = _play(north, south, tiles, seed)
        assert state.game_result() != GameResult.ONGOING


def test_piece_ids_follow_pieces_and_are_never_reused():
    for seed in range(5):
        state = _play("hard", "medium", None, seed)
        lost = [
            event.piece
            for turn in state.public_log
            for event in turn.events
            if event.kind == LogKind.LOSE
        ]
        on_board = [i for p in Player for i in state.piece_ids[p]]
        # every piece lost once, and none of them still on the board
        assert len(lost) == len(set(lost))
        assert not set(lost) & set(on_board)
        assert all(i is not None and i < state.next_piece_id for i in lost + on_board)
        for player in Player:
            assert len(state.piece_ids[player]) == len(state.positions[player])


def _other(player: Player) -> Player:
    return Player.S if player == Player.N else Player.N


def _claimed(state: State, claimer: Player, tile: Tile) -> Claim:
    """Log a claim of `tile` by the claimer's first piece at the other's first piece."""
    start = state.positions[claimer][0]
    target = state.positions[_other(claimer)][0]
    state.new_log_turn(claimer)
    state.log(LogKind.CLAIM, claimer, tile, piece=state.piece_at(start))
    return Claim(start, tile, target)


def _game(seed: int = 0) -> State:
    random.seed(seed)
    state = new_state(
        {p: 0 for p in Player},
        [Tile.FIREBALL, Tile.HARVESTER, Tile.HOOK, Tile.KNIVES, Tile.BACKSTABBER],
        Player.N,
        {p: p.value for p in Player},
    )
    # put the pieces where they can't reach each other
    state.positions = {
        Player.N: [Square(0, 0), Square(0, 4)],
        Player.S: [Square(4, 0), Square(4, 4)],
    }
    # nothing reflects a harvester, and nobody's revealed
    state.tiles_on_board[Player.S] = [Tile.FIREBALL, Tile.FIREBALL]
    return state


def _respond(bot: Bot, claim: Claim) -> Response | Tile:
    return asyncio.run(
        bot.choose_response([Response.ACCEPT, Response.CHALLENGE], "", claim)
    )


def test_medium_always_challenges_a_claim_it_can_see_is_impossible():
    state = _game()
    # every harvester is in plain sight to south
    state.tiles_in_hand[Player.S] = [Tile.HARVESTER, Tile.HARVESTER]
    state.discard = [Tile.HARVESTER]
    state.tiles_on_board[Player.N] = [Tile.KNIVES, Tile.KNIVES]
    claim = _claimed(state, Player.N, Tile.HARVESTER)
    for seed in range(20):
        bot = Bot("medium", delay=0, rng=random.Random(seed))
        bot.start_game(state, Player.S)
        assert _respond(bot, claim) == Response.CHALLENGE


def test_medium_lets_a_piece_keep_a_claim_it_let_stand_before():
    state = _game()
    first = _claimed(state, Player.N, Tile.HARVESTER)
    claim = _claimed(state, Player.N, Tile.HARVESTER)
    assert claims_since_exchange(
        state, state.piece_at(first.start), answering=True
    ) == [Tile.HARVESTER]
    for seed in range(20):
        bot = Bot("medium", delay=0, rng=random.Random(seed))
        bot.start_game(state, Player.S)
        assert _respond(bot, claim) == Response.ACCEPT


def test_medium_challenges_again_once_the_piece_may_have_exchanged():
    state = _game()
    first = _claimed(state, Player.N, Tile.HARVESTER)
    state.log(LogKind.EXCHANGE, Player.N, piece=state.piece_at(first.start))
    claim = _claimed(state, Player.N, Tile.HARVESTER)
    answers = set()
    for seed in range(40):
        bot = Bot("medium", delay=0, rng=random.Random(seed))
        bot.start_game(state, Player.S)
        answers.add(_respond(bot, claim))
    assert answers == {Response.ACCEPT, Response.CHALLENGE}


def test_a_revealed_tile_is_believed_or_caught_for_certain():
    state = _game()
    state.tiles_on_board[Player.N] = [Tile.HARVESTER, Tile.KNIVES]
    state.tiles_on_board_revealed[Player.N] = [True, False]
    true_claim = _claimed(state, Player.N, Tile.HARVESTER)
    lie = _claimed(state, Player.N, Tile.HOOK)
    for level in ("medium", "hard"):
        for seed in range(10):
            bot = Bot(level, delay=0, rng=random.Random(seed))
            bot.start_game(state, Player.S)
            assert _respond(bot, true_claim) == Response.ACCEPT
            assert _respond(bot, lie) == Response.CHALLENGE


def test_every_level_reflects_with_the_real_tile():
    state = _game()
    state.positions = {
        Player.N: [Square(1, 1), Square(0, 4)],
        Player.S: [Square(2, 1), Square(4, 4)],
    }
    state.tiles_on_board[Player.S] = [Tile.KNIVES, Tile.FIREBALL]
    claim = _claimed(state, Player.N, Tile.KNIVES)
    for level in LEVELS:
        bot = Bot(level, delay=0, rng=random.Random(0))
        bot.start_game(state, Player.S)
        answer = asyncio.run(
            bot.choose_response(
                [Response.ACCEPT, Response.CHALLENGE, Tile.KNIVES], "", claim
            )
        )
        assert answer == Tile.KNIVES


def test_hard_thinks_a_claim_likelier_a_lie_the_fewer_copies_could_be_theirs():
    state = _game()
    state.tiles_on_board[Player.N] = [Tile.KNIVES, Tile.KNIVES]
    piece = state.positions[Player.N][0]
    view = state.player_view(Player.S)

    plain = lie_chance(view, Player.S, state.piece_at(piece), Tile.HOOK, Counter())
    # south now holds two of the three hooks
    state.tiles_in_hand[Player.S] = [Tile.HOOK, Tile.HOOK]
    view = state.player_view(Player.S)
    scarce = lie_chance(view, Player.S, state.piece_at(piece), Tile.HOOK, Counter())
    assert scarce > plain
    # and every hook seen means certainly a lie
    state.discard = [Tile.HOOK]
    view = state.player_view(Player.S)
    assert lie_chance(view, Player.S, state.piece_at(piece), Tile.HOOK, Counter()) == 1


def test_bots_never_tell_a_lie_everyone_can_see_is_one():
    state = _game()
    state.current_player, state.other_player = Player.S, Player.N
    state.coins = {Player.N: 20, Player.S: 20}
    # every knives is lost, so no one can claim them
    state.discard = [Tile.KNIVES, Tile.KNIVES, Tile.KNIVES]
    state.positions = {
        Player.N: [Square(2, 2), Square(0, 4)],
        Player.S: [Square(3, 2), Square(4, 4)],
    }
    for level in ("medium", "hard"):
        for seed in range(30):
            bot = Bot(level, delay=0, rng=random.Random(seed))
            bot.start_game(state, Player.S)
            _, action, _ = asyncio.run(bot.choose_turn())
            assert action != Tile.KNIVES


def test_a_backstab_kill_on_an_exchange_leaves_the_backstabber_where_it_was():
    # it used to be taken for a move onto the exchange, and crash looking for the piece
    state = _game()
    exchange = state.exchange_positions[0]
    # north's behind is up the board: the enemy on the exchange is behind it
    start = Square(exchange.row + 1, exchange.col)
    state.positions = {
        Player.N: [start, Square(0, (exchange.col + 2) % 5)],
        Player.S: [exchange, Square(4, (exchange.col + 2) % 5)],
    }
    state.tiles_on_board[Player.N] = [Tile.BACKSTABBER, Tile.FIREBALL]
    state.coins = {Player.N: 5, Player.S: 5}
    players = {p: Bot("easy", delay=0) for p in Player}
    for player, bot in players.items():
        bot.start_game(state, player)
    logged = state.log(LogKind.CLAIM, Player.N, Tile.BACKSTABBER)
    asyncio.run(
        _resolve_action(
            start,
            Tile.BACKSTABBER,
            exchange,
            state,
            {p: b for p, b in players.items()},
            logged,
        )
    )
    # the backstabber stayed put, and south lost the tile on the exchange (which a tile
    # from their hand then replaced)
    assert start in state.positions[Player.N]
    assert state.discard == [Tile.FIREBALL]


def test_hard_beats_easy_mostly():
    wins = 0
    for seed in range(20):
        state = _play("hard", "easy", None, 100 + seed)
        wins += state.game_result() == GameResult.NORTH_WINS
    assert wins >= 14
