from enum import Enum
from typing import NamedTuple


# There are two players:
#   North - displayed on top
#   South - displayed on bottom
#
# the enum values must match the javascript & css values
class Player(str, Enum):
    N = "north"
    S = "south"

    def format_for_log(self) -> str:
        return self.value.upper()


def other_player(p: Player) -> Player:
    return Player.S if p == Player.N else Player.N


ROWS = 5
COLUMNS = 5


class Square(NamedTuple):
    """A coordinate on the board."""

    row: int
    col: int

    def on_board(self) -> bool:
        """True if the square is in-bounds on the board."""
        return 0 <= self.row < ROWS and 0 <= self.col < COLUMNS

    @classmethod
    def from_list(cls, coords: list) -> "Square":
        assert len(coords) == 2
        row, col = coords
        return cls(row, col)

    def format_for_log(self) -> str:
        """The player-facing log is 1-indexed."""
        return f"({self.row + 1}, {self.col + 1})"


class Tile(str, Enum):
    """
    The game pieces.

    Each tile enables one special action.

    You can always do the special action of any tile, but will lose a life
    if challenged and you aren't that tile.
    """

    # ORIGINAL TILES

    # move 1 & gain $3
    FLOWER = "🀥"

    # pull enemy to yourself at a Queen move & steal $2
    HOOK = "🀍"

    # move 1-2, gain $2, reveal 1 unused
    BIRD = "🀐"

    # $3 to kill in a 3x3 square
    # around an empty square 2 squares away in a cardinal direction
    GRENADES = "🀛"

    # spend:
    #   - $3 to kill @ distance range 1
    #   - $5 to kill @ distance range 2
    KNIVES = "🀒"

    # EXPANSION TILES

    # $3 to shoot a fireball diagonally
    # explodes on impact and destroys a 3x3 square
    FIREBALL = "🀙"

    # $1 to move 1, knockback adjacent enemies
    # knockback kills if the enemy can't move
    RAM = "🀎"

    # move 1 forward, gain $4
    HARVESTER = "🀨"

    # spend $3 to kill anything behind you
    # OR: move 2, gain $1
    BACKSTABBER = "🀇"

    # frost: $3 to kill everything in the ring 2 squares away, own tiles too, and ice it
    # a tile moving onto ice slides on the same way until it's off the ice or blocked
    FROST = "🀩"

    # $1 to shine a beam straight (not diagonally) to the edge, revealing every tile
    # it crosses; the first tile it reaches can reflect it with a sunbeam
    SUNBEAM = "🀧"

    # steal $4, swap places with target
    THIEF = "🀌"

    # move 2, gain $0, take turn again after exchange
    # leave web behind
    #   - enemy crossing it loses a turn
    #   - blocks fireballs; destroyed by fireballs
    SPIDER = "🀗"

    # SPECIAL TILES

    # Represents a tile with value unknown to a player
    # there is a private state known only to the game engine with no hidden tiles;
    # each player has a view with some of the tiles replaced with HIDDEN
    HIDDEN = "🀫"

    def __str__(self) -> str:
        return f"{self.value} ({self.name.lower()})"


class OtherAction(str, Enum):
    """
    These actions are always allowed for any tile.
    """

    # Move 1 square and gain 1 mana
    MOVE = "↕"

    # Kill any enemy tile, forced when a player's coins reach the smite cost.
    # Never chosen as a turn's action: it only marks the targets of a smite.
    SMITE = "⚡"

    def __str__(self) -> str:
        return f"{self.value} ({self.name.lower()})"


# An action is: use a tile power or a different action
Action = Tile | OtherAction


class ActionAndTarget(NamedTuple):
    """An action and its target, chosen together in one click."""

    action: Action
    target: Square


class Claim(NamedTuple):
    """
    A claim being answered: the claimer's tile at `start` claims `action` on `target`.
    `reflected` when the target's tile has claimed to reflect it, and it's the
    reflect being answered.
    """

    start: Square
    action: Action
    target: Square
    reflected: bool = False


class GameResult(str, Enum):
    ONGOING = "Ongoing"
    NORTH_WINS = "North Player Wins!"
    SOUTH_WINS = "South Player Wins!"

    # a draw is possible if both players are simultaneously killed by a chromatic grenade
    DRAW = "Draw"


class Response(str, Enum):
    ACCEPT = "✓"
    CHALLENGE = "🚩"

    def __str__(self) -> str:
        return f"{self.value} ({self.name.lower()})"


class OutEventType(str, Enum):
    # TODO explain
    # must match javascript

    STATE_CHANGE = "STATE_CHANGE"

    PROMPT = "PROMPT"

    SELECTION_CHANGE = "SELECTION_CHANGE"

    HIGHLIGHT_CHANGE = "HIGHLIGHT_CHANGE"

    MATCH_CHANGE = "MATCH_CHANGE"

    CLOCK = "CLOCK"

    # who has paused the match (see clock.Pause)
    PAUSE = "PAUSE"
