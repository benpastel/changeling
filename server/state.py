from enum import Enum
from random import shuffle

from pydantic import BaseModel, computed_field

from server.constants import (
    Player,
    Square,
    GameResult,
    Tile,
    Action,
    other_player,
)
from server.config import (
    choose_bonus_amount,
    choose_bonus_reveal,
    choose_start_coins,
    choose_smite_cost,
    bonus_and_exchange_positions,
    choose_start_positions,
    choose_tiles_in_game,
    NEGATIVE_COINS_OK,
)


class LogKind(str, Enum):
    """What a log event records.  Must match the javascript in renderState.js."""

    CLAIM = "claim"  # claimed a tile's action; `action` is the tile
    MOVE = "move"  # used an action that isn't a claim
    REFLECT = "reflect"  # claimed a tile to reflect the opponent's claim
    CHALLENGE = "challenge"
    REVEAL = "reveal"  # a challenged tile was revealed; `action` is the tile
    LOSE = "lose"  # lost a tile on board; `action` is the tile
    SMITE = "smite"
    BONUS = (
        "bonus"  # started the turn on the bonus square; `count` unused tiles revealed
    )
    EXCHANGE = "exchange"  # may have exchanged with an exchange square
    WEB = "web"  # caught in a web
    SKIP = "skip"  # skipped their turn
    AGAIN = "again"  # goes again
    X2 = "x2"  # moved the x2 to `action`
    WIN = "win"
    DRAW = "draw"


class LogEvent(BaseModel):
    """One public event, done by (or happening to) `player`."""

    kind: LogKind
    player: Player | None = None
    action: Action | None = None
    # a claim or reflect that was caught as a bluff, or reflected, so didn't happen
    cancelled: bool = False
    # how each player's coins changed
    coins: dict[Player, int] = {}
    count: int = 0
    # the piece that claimed, reflected, was revealed, was lost, or may have exchanged
    # (see State.piece_ids)
    piece: int | None = None


class LogTurn(BaseModel):
    """The events of one turn, or of the end of the game when `player` is None."""

    player: Player | None
    events: list[LogEvent] = []


class State(BaseModel):
    """
    The between-turn state of the game (board, tiles, coins, log).

    There are 3 versions of the state:
        - a private state known only to the server that includes all the tiles
        - each player's view on the state where some of the tiles are hidden
    """

    # the set of 5 tiles in use for this game
    tiles_in_game: list[Tile]

    # Each player starts with 4 tiles in hand.  They then place 2 on the board.
    # When a player runs out of tiles they lose.
    tiles_in_hand: dict[Player, list[Tile]]

    # The tiles in play on the board for each player.
    # See `positions` for the corresponding tile locations.
    tiles_on_board: dict[Player, list[Tile]]

    # Players can see their own tiles and any tile that has been revealed.
    # These correspond to `tiles_on_board`.
    tiles_on_board_revealed: dict[Player, list[bool]]

    # The square of each tile in play on the board for each player.
    # See `tiles_on_board` for the corresponding tile.
    positions: dict[Player, list[Square]]

    # A public id for each tile in play, corresponding to `positions`, that stays with
    # the piece as it moves and changes identity, and is never reused, so a piece's
    # claims can be followed through the log.
    piece_ids: dict[Player, list[int]]
    next_piece_id: int

    # The two tiles on each exchange square.
    # These correspond by index to exchange_positions.
    exchange_tiles: list[list[Tile]]
    exchange_tiles_revealed: dict[Player, list[bool]]

    # The remaining tile tiles are face-down off-board; can be revealed by bird.
    unused_tiles: list[Tile]
    unused_revealed: dict[Player, list[bool]]

    # The list of tiles that have been revealed when a player lost a life.
    # These tiles stay face-up and are never reshuffled.
    discard: list[Tile]

    # points used to cast tiles
    coins: dict[Player, int]

    # Web squares dropped by spiders for each player.
    # if an opponent passes through, they'll lose their next turn (doesn't stack)
    webs: dict[Player, list[Square]]
    skip_next_turn: dict[Player, bool]
    go_again: bool

    # Iced squares, left by ice; anyone's tile moving onto one slides on (see
    # actions.slide).  Ice never melts.
    ice: list[Square] = []  # when a spider exchanges, the current player may go again

    # log of public information, grouped by turn
    public_log: list[LogTurn]

    # current player is the player whose turn it currently is; other_player is the other
    # redundant attributes for easier communication with frontend
    current_player: Player
    other_player: Player

    match_score: dict[Player, int]

    # each player's display name, for the log
    names: dict[Player, str]

    # a square whose tile just died, left empty while its player chooses the
    # replacement from their hand
    vacant: dict[Player, Square] = {}

    # set when the game is over: every tile is shown to both players
    revealed_all: bool = False

    # position of the exchange squares that allow swapping tiles
    exchange_positions: list[Square]

    # Position and value of the bonus square
    # eventually the effect of the bonus square should be configurable in lobby
    # for now we hardcode it
    bonus_position: Square
    bonus_amount: int  # extra coin per-turn from bonus square
    bonus_reveal: int  # unused cards revealed per-turn from bonus square
    x2_tile: Tile | None  # tile with doubled effectiveness, set via bonus square
    smite_cost: int  # automatically smite when money reaches this amount

    game_score: dict[Player, int] = {Player.N: 0, Player.S: 0}

    @computed_field  # type: ignore[misc]
    @property
    def hidden_tiles(self) -> list[Tile]:
        """
        A sorted list of all tiles that are hidden from the player.

        Calculated by process of elimination, so that each player's state view can compute the list
        without knowing the other player's tiles.
        """

        # we can assume that any unknown tiles are already replaced by Tile.HIDDEN
        # so start by finding all non-hidden tiles, and then remove those from the full list

        viewed_tiles = [
            tile
            for tile in self.unused_tiles
            + self.tiles_in_hand[self.current_player]
            + self.tiles_in_hand[other_player(self.current_player)]
            + self.tiles_on_board[self.current_player]
            + self.tiles_on_board[other_player(self.current_player)]
            + self.exchange_tiles[0]
            + self.exchange_tiles[1]
            + self.discard
        ]
        assert len(viewed_tiles) == 15
        visible_tiles = [tile for tile in viewed_tiles if tile != Tile.HIDDEN]

        # make sure to remove the correct number of copies of each visible tile
        tiles = [tile for tile in self.tiles_in_game for _ in range(3)]
        for tile in visible_tiles:
            tiles.remove(tile)

        return sorted(tiles)

    def tile_at(self, square: Square) -> Tile:
        """The tile occupying on the board at this square.  Error if there isn't one."""
        maybe_tile = self.maybe_tile_at(square)
        if maybe_tile is None:
            raise ValueError(f"Expected tile at {square}")
        return maybe_tile

    def maybe_tile_at(self, square: Square) -> Tile | None:
        for player in Player:
            for s, other_square in enumerate(self.positions[player]):
                if other_square == square:
                    return self.tiles_on_board[player][s]
        return None

    def reveal_at(self, square: Square) -> None:
        """Reveal the tile at square.  Error if there isn't one."""
        for player in Player:
            for s, other_square in enumerate(self.positions[player]):
                if other_square == square:
                    self.tiles_on_board_revealed[player][s] = True
                    return
        raise ValueError(f"Expected tile at {square}")

    def reveal_unused(self) -> bool:
        """
        Reveal 1 unused tile to current player, or do nothing if they are all revealed.
        Return whether a new tile was revealed.
        """
        reveal_list = self.unused_revealed[self.current_player]
        if all(reveal_list):
            # already revealed all unused tiles
            return False

        next_idx = reveal_list.index(False)
        reveal_list[next_idx] = True
        return True

    def player_at(self, square: Square) -> Player:
        """
        The player owning a tile occupying that square. ValueError if there isn't one.
        """
        maybe_player = self.maybe_player_at(square)
        if maybe_player is None:
            raise ValueError(f"Expected tile at {square}")
        return maybe_player

    def piece_at(self, square: Square) -> int:
        """The id of the piece on this square.  Error if there isn't one."""
        for player in Player:
            if square in self.positions[player]:
                return self.piece_ids[player][self.positions[player].index(square)]
        raise ValueError(f"Expected tile at {square}")

    def maybe_player_at(self, square: Square) -> Player | None:
        for player in Player:
            for s, other_square in enumerate(self.positions[player]):
                if other_square == square:
                    return player
        return None

    def all_positions(self) -> list[Square]:
        """All squares with a tile on board, regardless of player"""
        return self.positions[Player.N] + self.positions[Player.S]

    def all_webs(self) -> list[Square]:
        """All squares with a web on board, regardless of player"""
        return self.webs[Player.N] + self.webs[Player.S]

    def new_log_turn(self, player: Player | None) -> None:
        """Start grouping log events under a new turn."""
        self.public_log.append(LogTurn(player=player))

    def log(
        self,
        kind: LogKind,
        player: Player | None = None,
        action: Action | None = None,
        coins: dict[Player, int] | None = None,
        count: int = 0,
        piece: int | None = None,
    ) -> LogEvent:
        """
        Log an event in the current turn.

        Returns the event, which can still be updated (e.g. cancelled) as the turn goes on.
        """
        if not self.public_log:
            self.new_log_turn(self.current_player)
        event = LogEvent(
            kind=kind,
            player=player,
            action=action,
            coins=coins or {},
            count=count,
            piece=piece,
        )
        self.public_log[-1].events.append(event)
        return event

    def game_result(self) -> GameResult:
        """
        See if anyone has won the game.
        """
        north_dead = len(self.tiles_on_board[Player.N]) == 0
        south_dead = len(self.tiles_on_board[Player.S]) == 0
        if north_dead and south_dead:
            return GameResult.DRAW
        elif south_dead:
            return GameResult.NORTH_WINS
        elif north_dead:
            return GameResult.SOUTH_WINS
        else:
            return GameResult.ONGOING

    def player_view(self, player: Player) -> "State":
        """
        Return a copy of self with all hidden tiles replaced by Tile.HIDDEN

        This represents the player's knowledge of the state.
        """
        if self.revealed_all:
            return self.model_copy()
        opponent = other_player(player)

        # we know the number of tiles in the opponent's hand but not their identity
        opponent_hand = [Tile.HIDDEN for tile in self.tiles_in_hand[opponent]]

        # we know the number and location of tiles on the opponent's board but not their
        # identity; unless they are revealed
        opponent_board = [
            tile if revealed else Tile.HIDDEN
            for tile, revealed in zip(
                self.tiles_on_board[opponent],
                self.tiles_on_board_revealed[opponent],
                strict=True,
            )
        ]

        # we can see exchange tiles if they've been revealed to us
        exchange_tiles = [
            tiles if revealed else [Tile.HIDDEN for _ in tiles]
            for tiles, revealed in zip(
                self.exchange_tiles, self.exchange_tiles_revealed[player], strict=True
            )
        ]

        unused_tiles = [
            tile if revealed else Tile.HIDDEN
            for tile, revealed in zip(
                self.unused_tiles, self.unused_revealed[player], strict=True
            )
        ]

        return State(
            tiles_in_game=self.tiles_in_game,
            tiles_in_hand={
                player: self.tiles_in_hand[player],
                opponent: opponent_hand,
            },
            tiles_on_board={
                player: self.tiles_on_board[player],
                opponent: opponent_board,
            },
            exchange_tiles=exchange_tiles,
            # all tile positions are public knowledge
            positions=self.positions,
            piece_ids=self.piece_ids,
            next_piece_id=self.next_piece_id,
            # we can't see the unused tiles
            unused_tiles=unused_tiles,
            # we can see everything else
            unused_revealed=self.unused_revealed,
            tiles_on_board_revealed=self.tiles_on_board_revealed,
            exchange_tiles_revealed=self.exchange_tiles_revealed,
            discard=self.discard,
            public_log=self.public_log,
            current_player=self.current_player,
            other_player=self.other_player,
            coins=self.coins,
            webs=self.webs,
            ice=self.ice,
            skip_next_turn=self.skip_next_turn,
            go_again=self.go_again,
            match_score=self.match_score,
            names=self.names,
            vacant=self.vacant,
            game_score=self.game_score,
            bonus_position=self.bonus_position,
            bonus_amount=self.bonus_amount,
            bonus_reveal=self.bonus_reveal,
            smite_cost=self.smite_cost,
            x2_tile=self.x2_tile,
            exchange_positions=self.exchange_positions,
        )

    def check_consistency(self) -> None:
        """
        Check that the tiles are consistent.
        """

        # check there are exactly 3 of each tile
        tile_counts = {tile: 0 for tile in self.tiles_in_game}
        for tile_list in self.tiles_in_hand.values():
            assert 0 <= len(tile_list) <= 2
            for tile in tile_list:
                tile_counts[tile] += 1

        for tile_list in self.tiles_on_board.values():
            assert 0 <= len(tile_list) <= 2
            for tile in tile_list:
                tile_counts[tile] += 1

        for tile in self.discard:
            tile_counts[tile] += 1

        for tile_1, tile_2 in self.exchange_tiles:
            tile_counts[tile_1] += 1
            tile_counts[tile_2] += 1

        assert len(self.unused_tiles) == 3
        for tile in self.unused_tiles:
            tile_counts[tile] += 1

        for tile in self.tiles_in_game:
            assert tile_counts[tile] == 3

        # check 0-2 tiles on board and in hand per player
        for player in Player:
            assert 0 <= len(self.tiles_in_hand[player]) <= 2
            assert 0 <= len(self.tiles_on_board[player]) <= 2
            assert len(self.piece_ids[player]) == len(self.positions[player])
            if len(self.tiles_on_board[player]) < 2:
                # tiles in hand should have been exhausted before the player starts
                # losing tiles on board
                assert len(self.tiles_in_hand[player]) == 0

        # check location for each tile on board
        assert all(
            square.on_board()
            for player in Player
            for tile, square in zip(
                self.tiles_on_board[player],
                self.positions[player],
                strict=True,
            )
        )

        # check tile locations are unique
        assert len(self.all_positions()) == len(set(self.all_positions()))

        if not NEGATIVE_COINS_OK:
            assert all(self.coins[player] >= 0 for player in Player)

        assert self.current_player != self.other_player

    def next_turn(self) -> None:
        self.current_player = other_player(self.current_player)
        self.other_player = other_player(self.other_player)

    def score_point(self, player: Player) -> None:
        """Register that a player has scored a point by making a kill."""
        self.game_score[player] += 1
        self.match_score[player] += 1

    def scratch(self) -> "State":
        """A copy to play actions out on, without touching this one (or its log)."""
        return self.model_copy(
            update={
                "positions": {p: list(v) for p, v in self.positions.items()},
                "piece_ids": {p: list(v) for p, v in self.piece_ids.items()},
                "coins": dict(self.coins),
                "tiles_on_board": {p: list(v) for p, v in self.tiles_on_board.items()},
                "tiles_on_board_revealed": {
                    p: list(v) for p, v in self.tiles_on_board_revealed.items()
                },
                "webs": {p: list(v) for p, v in self.webs.items()},
                "ice": list(self.ice),
                "unused_revealed": {
                    p: list(v) for p, v in self.unused_revealed.items()
                },
            }
        )


def new_state(
    match_score: dict[Player, int],
    tile_set: list[Tile] | None,
    first_player: Player,
    names: dict[Player, str],
) -> State:
    """
    Return a new state with the tiles randomly dealt.

    `tile_set` is the set of tiles in use, or None to randomize it along with everything else.
    """
    randomize = tile_set is None

    start_coins_per_player = choose_start_coins(randomize)
    smite_cost = choose_smite_cost(randomize)
    bonus_amount = choose_bonus_amount(randomize)
    bonus_reveal = choose_bonus_reveal(randomize)
    tiles_in_game = choose_tiles_in_game(tile_set)
    start_positions = choose_start_positions()
    bonus_position, exchange_positions = bonus_and_exchange_positions()

    start_coins = {
        Player.N: start_coins_per_player,
        Player.S: start_coins_per_player,
    }

    # 3 copies of each tile
    tiles: list[Tile] = [tile for tile in tiles_in_game for s in range(3)]

    # check that we didn't change the count of stuff in the rules and forget to change this method
    assert len(tiles) == 15

    # shuffle, then deal out the cards from fixed indices
    shuffle(tiles)

    x2_tile = None  # TODO: x2 tile no longer supported; remove all references

    return State(
        tiles_in_game=tiles_in_game,
        tiles_in_hand={
            Player.N: tiles[0:2],
            Player.S: tiles[2:4],
        },
        tiles_on_board={Player.N: tiles[4:6], Player.S: tiles[6:8]},
        tiles_on_board_revealed={Player.N: [False, False], Player.S: [False, False]},
        positions=start_positions,
        piece_ids={Player.N: [0, 1], Player.S: [2, 3]},
        next_piece_id=4,
        exchange_tiles=[
            [tiles[8], tiles[9]],
            [tiles[10], tiles[11]],
        ],
        exchange_tiles_revealed={Player.N: [False, False], Player.S: [False, False]},
        unused_tiles=tiles[12:15],
        unused_revealed={
            Player.N: [False, False, False],
            Player.S: [False, False, False],
        },
        discard=[],
        coins=start_coins,
        webs={Player.N: [], Player.S: []},  # no webs start on board
        skip_next_turn={Player.N: False, Player.S: False},
        go_again=False,
        public_log=[],
        current_player=first_player,
        other_player=other_player(first_player),
        match_score=match_score,
        names=names,
        exchange_positions=exchange_positions,
        bonus_position=bonus_position,
        bonus_amount=bonus_amount,
        bonus_reveal=bonus_reveal,
        x2_tile=x2_tile,
        smite_cost=smite_cost,
    )
