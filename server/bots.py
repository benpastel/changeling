"""
The bot, at three levels.

Every level sees only its own view of the game (State.player_view), and follows each
piece's claims through the log by the piece's id.

  easy    a little better than random, for someone learning the rules: often a random
          true move, otherwise its best; lies and challenges now and then, at random
  medium  plays its best true move, greedily, with a little care not to walk into an
          attack; sometimes lies when the lie looks better.  Challenges a claim that
          can't be true, never re-challenges a piece's claim it let stand before, and
          otherwise challenges at a fixed rate
  hard    weighs everything by expected value: what each enemy piece probably is (from
          the copies it can't see, and the piece's claims), whether a claim is worth
          challenging, and whether a lie is worth telling, keeping its lies consistent
          and lying now and then even with a good true move

Values are in coins; a tile lost or killed is worth the smite cost, since that's what
coins buy, or much more when it's the last.
"""

import asyncio
from collections import Counter
import math
import os
import random

from server.actions import (
    take_action,
    reflect_action,
    valid_targets,
    _explosion_hits,
    _take_ram_action,
)
from server.constants import (
    Action,
    Claim,
    OtherAction,
    Player,
    Response,
    Square,
    Tile,
    other_player,
)
from server.seat import DummySeat
from server.state import LogKind, State

LEVELS = ("easy", "medium", "hard")
DEFAULT_LEVEL = "easy"

# seconds the bot takes over each decision, so a person can follow its turn;
# set BOT_DELAY=0.01 for fast testing
BOT_DELAY = float(os.environ.get("BOT_DELAY", "1"))

# claims that can be reflected by the same tile, when they hit an enemy tile
REFLECTABLE = {Tile.KNIVES, Tile.BACKSTABBER, Tile.HOOK, Tile.THIEF, Tile.FIREBALL}
# claims that kill or steal, which an enemy piece might make against us next turn
HARMFUL = {
    Tile.KNIVES,
    Tile.BACKSTABBER,
    Tile.FIREBALL,
    Tile.GRENADES,
    Tile.RAM,
    Tile.HOOK,
    Tile.THIEF,
}
# roughly how good each tile is to hold, in coins, before what it can do right now
TILE_WORTH = {
    Tile.FIREBALL: 3,
    Tile.KNIVES: 3,
    Tile.BACKSTABBER: 3,
    Tile.GRENADES: 2.5,
    Tile.HOOK: 2.5,
    Tile.THIEF: 2,
    Tile.HARVESTER: 2,
    Tile.FLOWER: 1.5,
    Tile.BIRD: 1.5,
    Tile.RAM: 1.5,
    Tile.TRICKSTER: 1,
    Tile.SPIDER: 1,
}

# how much more likely a piece is to be a tile it has claimed, unchallenged
CLAIM_EVIDENCE = 3.0
# how often anyone claims a tile they don't have, as far as the bot guesses
BLUFF_RATE = 0.12
# hard: how far below its best it will stray, in coins, and how often it tells a
# nearly-as-good lie anyway
TEMPERATURE = 0.7
CONFUSION = 0.05


# ------------------------------------------------------------------ knowledge


def unseen_counts(view: State, me: Player) -> dict[Tile, int]:
    """How many copies of each tile in the game `me` can't see anywhere."""
    them = other_player(me)
    seen = (
        view.tiles_in_hand[me]
        + view.tiles_on_board[me]
        + view.tiles_on_board[them]
        + [t for pair in view.exchange_tiles for t in pair]
        + view.unused_tiles
        + view.discard
    )
    counts = {tile: 3 for tile in view.tiles_in_game}
    for tile in seen:
        if tile in counts:
            counts[tile] -= 1
    return {tile: max(0, n) for tile, n in counts.items()}


def public_counts(view: State, me: Player) -> dict[Tile, int]:
    """How many copies of each tile both players can see: lost, or revealed on board."""
    counts = {tile: 0 for tile in view.tiles_in_game}
    shown = list(view.discard)
    for player in Player:
        for tile, revealed in zip(
            view.tiles_on_board[player], view.tiles_on_board_revealed[player]
        ):
            if revealed and tile != Tile.HIDDEN:
                shown.append(tile)
    for tile in shown:
        if tile in counts:
            counts[tile] += 1
    return counts


def claims_since_exchange(
    view: State, piece: int, answering: bool = False
) -> list[Action]:
    """
    What a piece has claimed, or claimed to reflect, since it last may have exchanged:
    claims that weren't caught, since a piece caught lying is lost.  `answering` leaves
    out its latest claim, the one being answered.
    """
    claims: list[Action] = []
    for turn in view.public_log:
        for event in turn.events:
            if event.piece != piece:
                continue
            if event.kind == LogKind.EXCHANGE:
                claims = []
            elif event.kind in (LogKind.CLAIM, LogKind.REFLECT) and event.action:
                claims.append(event.action)
    return claims[:-1] if answering else claims


def beliefs(
    view: State, me: Player, answering: int | None = None
) -> dict[int, dict[Tile, float]]:
    """
    For each enemy piece on the board, the chance it's each tile: a revealed piece is
    what it shows; otherwise each tile in proportion to the copies we can't see, made
    more likely by the piece's unchallenged claims of it (but not by the claim we're
    `answering`, if it's that piece's).
    """
    them = other_player(me)
    unseen = unseen_counts(view, me)
    result: dict[int, dict[Tile, float]] = {}
    for piece, tile in zip(view.piece_ids[them], view.tiles_on_board[them]):
        if tile != Tile.HIDDEN:
            result[piece] = {tile: 1.0}
            continue
        weights = {t: float(n) for t, n in unseen.items()}
        claimed = claims_since_exchange(view, piece, piece == answering)
        for action in set(claimed):
            if isinstance(action, Tile) and action in weights:
                # claiming it again, unchallenged, is a little more evidence
                weights[action] *= CLAIM_EVIDENCE ** min(2, claimed.count(action))
        total = sum(weights.values())
        if total == 0:
            # we've miscounted somewhere; know nothing
            weights = {t: 1.0 for t in view.tiles_in_game}
            total = float(len(weights))
        result[piece] = {t: w / total for t, w in weights.items()}
    return result


def read_log(view: State, me: Player) -> Counter:
    """
    How the game has gone between us, for reading the opponent: our claims and their
    challenges of them, and our challenges and how many caught a lie.
    """
    them = other_player(me)
    counts: Counter = Counter()
    for turn in view.public_log:
        claimed = None
        challenger = None
        for event in turn.events:
            if event.kind in (LogKind.CLAIM, LogKind.REFLECT):
                claimed = event.action
                if event.player == me:
                    counts["our claims"] += 1
            elif event.kind == LogKind.CHALLENGE:
                challenger = event.player
                counts[
                    "their challenges" if challenger == them else "our challenges"
                ] += 1
            elif (
                event.kind == LogKind.REVEAL
                and challenger == me
                and event.action != claimed
            ):
                counts["lies caught"] += 1
    return counts


def lie_chance(view: State, me: Player, piece: int, tile: Tile, read: Counter) -> float:
    """
    How likely the enemy's claim of `tile` by `piece` is a lie: how often they've been
    caught lying when we challenged (from a prior of about one in six), more likely
    the fewer copies of the tile we can't see, and less likely if the piece has
    claimed it before unchallenged.
    """
    rate = (read["lies caught"] + 1) / (read["our challenges"] + 6)
    unseen = unseen_counts(view, me)
    total = sum(unseen.values())
    if total == 0 or unseen.get(tile, 0) == 0:
        return 1.0
    # an even share of the unknown copies leaves the rate as it is
    share = unseen[tile] / total
    even = 1 / len(view.tiles_in_game)
    chance = rate * (1 - share) / (1 - even)
    if tile in claims_since_exchange(view, piece, answering=True):
        chance *= 0.6
    return min(1.0, max(0.0, chance))


# ------------------------------------------------------------------- outcomes


def _sim(view: State, actor: Player) -> State:
    """A copy of the view to play an action out on, with `actor` to move."""
    return view.model_copy(
        update={
            "positions": {p: list(v) for p, v in view.positions.items()},
            "piece_ids": {p: list(v) for p, v in view.piece_ids.items()},
            "coins": dict(view.coins),
            "tiles_on_board": {p: list(v) for p, v in view.tiles_on_board.items()},
            "tiles_on_board_revealed": {
                p: list(v) for p, v in view.tiles_on_board_revealed.items()
            },
            "webs": {p: list(v) for p, v in view.webs.items()},
            "unused_revealed": {p: list(v) for p, v in view.unused_revealed.items()},
            "current_player": actor,
            "other_player": other_player(actor),
        }
    )


def kill_value(view: State, victim: Player) -> float:
    """What losing a tile costs `victim`: everything, if it's their last."""
    lives = len(view.tiles_on_board[victim]) + len(view.tiles_in_hand[victim])
    return 100.0 if lives <= 1 else float(view.smite_cost)


def _standing(state: State, player: Player) -> float:
    """What a position is worth to `player`, beyond the tiles: coins, and the bonus."""
    them = other_player(player)
    value = float(state.coins[player] - state.coins[them])
    on_bonus = state.maybe_player_at(state.bonus_position)
    if on_bonus == player:
        value += 0.6 * state.bonus_amount
    elif on_bonus == them:
        value -= 0.6 * state.bonus_amount
    # reaching the smite cost kills at once
    if state.coins[player] >= state.smite_cost:
        value += 2
    return value


def _score_hits(view: State, sim: State, actor: Player, hits: list[Square]) -> float:
    value = 0.0
    for hit in set(hits):
        owner = sim.maybe_player_at(hit)
        if owner == actor:
            value -= kill_value(view, actor)
        elif owner is not None:
            value += kill_value(view, owner)
    return value


def outcome(
    view: State, actor: Player, start: Square, action: Action, target: Square
) -> tuple[float, State]:
    """What `actor` gains by `action`, if it goes ahead, and the board after it."""
    sim = _sim(view, actor)
    hits = take_action(start, action, target, sim)
    value = _standing(sim, actor) - _standing(view, actor)
    value += _score_hits(view, sim, actor, hits)
    return value, sim


def reflected_outcome(
    view: State, claimer: Player, start: Square, action: Action, target: Square
) -> float:
    """What the claimer gains (usually loses) when the claim is reflected back."""
    sim = _sim(view, claimer)
    hits = reflect_action(start, action, target, sim)
    return (
        _standing(sim, claimer)
        - _standing(view, claimer)
        + _score_hits(view, sim, claimer, hits)
    )


def _enemy_hits(sim: State, start: Square, action: Action, target: Square) -> list:
    """Whom an attack would hit, without playing it out (except a ram's knockback)."""
    if action in (Tile.KNIVES, Tile.BACKSTABBER):
        return [target] if sim.maybe_player_at(target) is not None else []
    if action in (Tile.FIREBALL, Tile.GRENADES):
        return _explosion_hits(target, sim.all_positions())
    if action == Tile.RAM:
        return _take_ram_action(start, target, _sim(sim, sim.current_player))
    return []


def danger(
    sim: State,
    me: Player,
    chance: "dict[int, dict[Tile, float]] | None",
) -> float:
    """
    The worst the enemy can expect to do to `me` next turn from this board: each
    harmful thing an enemy piece can do, weighted by how likely it is to do it, which
    is the chance it is that tile (from `chance`, or a flat guess) plus a bluff.
    """
    them = other_player(me)
    worst = 0.0
    if not sim.positions[me] or not sim.positions[them]:
        # the game's over
        return worst
    if sim.coins[them] >= sim.smite_cost:
        worst = kill_value(sim, me)
    turn = _sim(sim, them)
    for start, piece in zip(turn.positions[them], turn.piece_ids[them]):
        for action, targets in valid_targets(start, turn).items():
            if not isinstance(action, Tile) or action not in HARMFUL:
                continue
            likely = (
                chance[piece].get(action, 0.0) + BLUFF_RATE
                if chance is not None and piece in chance
                else 0.3
            )
            for target in targets:
                if action in (Tile.HOOK, Tile.THIEF):
                    # a steal: theirs to gain, ours to lose
                    harm = 4.0 if action == Tile.HOOK else 8.0
                else:
                    hits = _enemy_hits(turn, start, action, target)
                    harm = sum(
                        kill_value(sim, me)
                        for h in hits
                        if turn.maybe_player_at(h) == me
                    )
                worst = max(worst, min(1.0, likely) * harm)
    return worst


# ------------------------------------------------------------------------ bot


class Bot:
    """Chooses as the level says, from its own view of the game it's told about."""

    def __init__(
        self,
        level: str = DEFAULT_LEVEL,
        delay: float = BOT_DELAY,
        rng: random.Random | None = None,
    ):
        assert level in LEVELS
        self.level = level
        self.delay = delay
        self.rng = rng or random.Random()
        self.seat = DummySeat()
        self._state: State | None = None
        self.me = Player.N
        # what we chose on each board we've chosen on, so as not to go round in circles
        self._chosen: dict[tuple, set] = {}
        # how often we've done what, over every game, for tuning
        self.stats: Counter = Counter()
        # how the earlier games of the match went between us (see read_log)
        self._past: Counter = Counter()

    def start_game(self, state: State, player: Player) -> None:
        if self._state is not None:
            self._past += read_log(self._state.player_view(self.me), self.me)
        self._state = state
        self.me = player
        self._chosen = {}

    @property
    def them(self) -> Player:
        return other_player(self.me)

    def view(self) -> State:
        assert self._state is not None
        return self._state.player_view(self.me)

    def _read(self, view: State) -> Counter:
        """How the match has gone between us so far (see read_log)."""
        return self._past + read_log(view, self.me)

    async def _pause(self, beats: float = 1) -> None:
        await asyncio.sleep(self.delay * beats)

    # ------------------------------------------------------------- the turn

    def _options(self, view: State) -> list[tuple[Square, Action, Square, bool]]:
        """Every (start, action, target), and whether it's true."""
        options = []
        for start, tile in zip(view.positions[self.me], view.tiles_on_board[self.me]):
            for action, targets in valid_targets(start, view).items():
                true = action == OtherAction.MOVE or action == tile
                options += [(start, action, target, true) for target in targets]
        return options

    def _challenge_chance(
        self, view: State, start: Square, action: Action, gain: float
    ) -> float:
        """How likely the enemy is to challenge our claim, as far as we can tell."""
        if action == OtherAction.MOVE:
            return 0.0
        if self.level != "hard":
            return 0.3
        assert isinstance(action, Tile)
        piece = view.piece_at(start)
        history = claims_since_exchange(view, piece)
        # how often they've challenged us, from a prior of about one in five
        read = self._read(view)
        chance = (read["their challenges"] + 1) / (read["our claims"] + 5)
        if action in history:
            chance *= 0.5
        elif history:
            chance *= 1.8
        if gain >= view.smite_cost:
            # a kill is worth checking
            chance += 0.15
        return min(1.0, chance)

    def _value(
        self,
        view: State,
        chance: "dict[int, dict[Tile, float]] | None",
        start: Square,
        action: Action,
        target: Square,
        true: bool,
    ) -> float:
        """What a choice of turn is worth, given what may be done about it."""
        gain, sim = outcome(view, self.me, start, action, target)
        value = gain - 0.5 * danger(sim, self.me, chance)
        if action == OtherAction.MOVE:
            return value
        assert isinstance(action, Tile)
        if not true and public_counts(view, self.me)[action] >= 3:
            # every copy is out in the open: we'd surely be caught
            return -kill_value(view, self.me)
        lose = kill_value(view, self.me)
        challenged = self._challenge_chance(view, start, action, gain)
        if true:
            # a wrong challenge costs them a tile
            value += challenged * kill_value(view, self.them)
        else:
            value = (1 - challenged) * value - challenged * lose
        # they may reflect it: likely, if that piece has claimed it before
        enemy = view.maybe_player_at(target)
        if action in REFLECTABLE and enemy == self.them:
            piece = view.piece_at(target)
            if chance is not None:
                reflects = chance.get(piece, {}).get(action, 0.0) + 0.05
            else:
                reflects = 0.8 if action in claims_since_exchange(view, piece) else 0.1
            back = reflected_outcome(view, self.me, start, action, target)
            value = (1 - reflects) * value + reflects * back
        return value

    async def choose_turn(self) -> tuple[Square, Action, Square]:
        await self._pause(2)
        view = self.view()
        options = self._options(view)
        trues = [o for o in options if o[3]]
        lies = [o for o in options if not o[3]]
        assert trues, "a move is always possible"
        rng = self.rng

        if self.level == "easy":
            if lies and rng.random() < 0.1:
                start, action, target, _ = rng.choice(lies)
            elif rng.random() < 0.6:
                start, action, target, _ = rng.choice(trues)
            else:
                start, action, target, _ = max(
                    trues, key=lambda o: outcome(view, self.me, o[0], o[1], o[2])[0]
                )
            self._count(view, start, action)
            return start, action, target

        # a turn we've had before, exactly: do something else this time, so two bots
        # (or a bot and a patient person) don't trade the same steal forever
        board = (
            tuple(tuple(view.positions[p]) for p in Player),
            tuple(view.coins[p] for p in Player),
            tuple(view.tiles_on_board[self.me]),
        )
        chosen = self._chosen.setdefault(board, set())
        fresh = [o for o in options if o[:3] not in chosen]
        if any(o[3] for o in fresh):
            options = fresh
            trues = [o for o in options if o[3]]
            lies = [o for o in options if not o[3]]
        start, action, target = self._choose(view, options, trues, lies)
        chosen.add((start, action, target))
        self._count(view, start, action)
        return start, action, target

    def _count(self, view: State, start: Square, action: Action) -> None:
        """Keep count of our moves, true claims, and lies, for tuning."""
        if action == OtherAction.MOVE:
            self.stats["move"] += 1
        elif view.maybe_tile_at(start) == action:
            self.stats["true claim"] += 1
        else:
            self.stats["lie"] += 1

    def _choose(
        self,
        view: State,
        options: list[tuple[Square, Action, Square, bool]],
        trues: list[tuple[Square, Action, Square, bool]],
        lies: list[tuple[Square, Action, Square, bool]],
    ) -> tuple[Square, Action, Square]:
        rng = self.rng
        chance = beliefs(view, self.me) if self.level == "hard" else None
        scored = [
            (self._value(view, chance, s, a, t, true) + rng.random(), (s, a, t, true))
            for s, a, t, true in (options if self.level == "hard" else trues)
        ]
        if self.level == "medium":
            # now and then, weigh the lies too
            if lies and rng.random() < 0.2:
                scored += [
                    (self._value(view, None, s, a, t, False), (s, a, t, False))
                    for s, a, t, _ in lies
                ]
            _, (start, action, target, _) = max(scored, key=lambda pair: pair[0])
            return start, action, target

        scored.sort(key=lambda pair: -pair[0])
        best = scored[0][0]
        # now and then, a plausible lie that's nearly as good, to keep them guessing
        if rng.random() < CONFUSION:
            close = [pair for pair in scored if not pair[1][3] and pair[0] >= best - 3]
            if close:
                _, (start, action, target, _) = close[0]
                return start, action, target
        # otherwise mostly the best, sometimes one nearly as good
        top = scored[:3]
        weights = [math.exp((value - best) / TEMPERATURE) for value, _ in top]
        _, (start, action, target, _) = rng.choices(top, weights)[0]
        return start, action, target

    # ------------------------------------------------------------- answers

    async def choose_response(
        self,
        possible_responses: list[Response | Tile],
        prompt: str,
        claim: Claim,
    ) -> Response | Tile:
        await self._pause()
        view = self.view()
        rng = self.rng
        if claim.reflected:
            return self._answer_reflect(view, claim)

        start, action, target, _ = claim
        mine = (
            view.maybe_tile_at(target)
            if view.maybe_player_at(target) == self.me
            else None
        )
        reflects = [r for r in possible_responses if isinstance(r, Tile)]
        if mine is not None and mine in reflects:
            # a true reflect
            return mine

        if self.level == "easy":
            if rng.random() < 0.15:
                return Response.CHALLENGE
            if reflects and rng.random() < 0.05:
                return reflects[0]
            return Response.ACCEPT

        assert isinstance(action, Tile)
        piece = view.piece_at(start)
        shown = view.maybe_tile_at(start)
        harm, _ = outcome(view, self.them, start, action, target)
        if shown != Tile.HIDDEN:
            return Response.ACCEPT if shown == action else Response.CHALLENGE
        if unseen_counts(view, self.me)[action] == 0:
            # every copy is accounted for elsewhere
            return Response.CHALLENGE

        if self.level == "medium":
            if action in claims_since_exchange(view, piece, answering=True):
                # we let it stand before
                return Response.ACCEPT
            if reflects and harm >= view.smite_cost and rng.random() < 0.1:
                return reflects[0]
            return Response.CHALLENGE if rng.random() < 0.3 else Response.ACCEPT

        # weigh accepting, challenging, and bluffing a reflect
        lie = lie_chance(view, self.me, piece, action, self._read(view))
        ours, theirs = kill_value(view, self.me), kill_value(view, self.them)
        values: dict[Response | Tile, float] = {
            Response.ACCEPT: -harm,
            Response.CHALLENGE: lie * theirs - (1 - lie) * (harm + ours),
        }
        for reflect in reflects:
            back = -reflected_outcome(view, self.them, start, action, target)
            caught = self._challenge_chance(view, target, reflect, back)
            values[reflect] = (1 - caught) * back - caught * (harm + ours)
        ranked = sorted(values.items(), key=lambda pair: -pair[1])
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 1 and rng.random() < 0.3:
            return ranked[1][0]
        return ranked[0][0]

    def _answer_reflect(self, view: State, claim: Claim) -> Response:
        """Our claim was reflected; challenge the reflect, or let it stand."""
        start, action, target, _ = claim
        rng = self.rng
        if self.level == "easy":
            return Response.CHALLENGE if rng.random() < 0.15 else Response.ACCEPT
        piece = view.piece_at(target)
        shown = view.maybe_tile_at(target)
        if shown != Tile.HIDDEN:
            return Response.ACCEPT if shown == action else Response.CHALLENGE
        assert isinstance(action, Tile)
        if unseen_counts(view, self.me)[action] == 0:
            return Response.CHALLENGE
        if self.level == "medium":
            if action in claims_since_exchange(view, piece, answering=True):
                return Response.ACCEPT
            return Response.CHALLENGE if rng.random() < 0.3 else Response.ACCEPT
        lie = lie_chance(view, self.me, piece, action, self._read(view))
        back = reflected_outcome(view, self.me, start, action, target)
        ahead, _ = outcome(view, self.me, start, action, target)
        ours, theirs = kill_value(view, self.me), kill_value(view, self.them)
        accept = back
        challenge = lie * (ahead + theirs) + (1 - lie) * (back - ours)
        return Response.CHALLENGE if challenge > accept else Response.ACCEPT

    # ------------------------------------------------------------- tiles

    def _tile_value(self, view: State, square: Square, tile: Tile) -> float:
        """How good `tile` would be on `square`: in general, and what it could do now."""
        if not view.positions[self.them]:
            return TILE_WORTH.get(tile, 1)
        sim = _sim(view, self.me)
        index = (
            sim.positions[self.me].index(square)
            if square in sim.positions[self.me]
            else None
        )
        if index is None:
            # a replacement, on the empty square
            sim.positions[self.me].append(square)
            sim.tiles_on_board[self.me].append(tile)
            sim.tiles_on_board_revealed[self.me].append(False)
            sim.piece_ids[self.me].append(sim.next_piece_id)
        else:
            sim.tiles_on_board[self.me][index] = tile
        best = 0.0
        for action, targets in valid_targets(square, sim).items():
            if action == tile:
                for target in targets:
                    best = max(best, outcome(sim, self.me, square, action, target)[0])
        return TILE_WORTH.get(tile, 1) + 0.5 * best

    async def choose_exchange(self, choices: list[Tile], prompt: str) -> Tile:
        await self._pause()
        if self.level == "easy":
            return self.rng.choice(choices)
        view = self.view()
        # ours is last; the exchange is where it stands
        square = next(
            s
            for s, tile in zip(view.positions[self.me], view.tiles_on_board[self.me])
            if s in view.exchange_positions and tile == choices[-1]
        )
        return max(choices, key=lambda tile: self._tile_value(view, square, tile))

    async def choose_square_or_hand(
        self,
        possible_squares: list[Square],
        possible_hand_tiles: list[Tile],
        prompt: str,
    ) -> Square | Tile:
        await self._pause()
        view = self.view()
        if self.level == "easy":
            choices: list[Square | Tile] = [*possible_squares, *possible_hand_tiles]
            return self.rng.choice(choices)
        if possible_hand_tiles:
            # a replacement for the empty square
            square = view.vacant[self.me]
            return max(
                possible_hand_tiles,
                key=lambda tile: self._tile_value(view, square, tile),
            )

        # a tile to lose: the one worth least, sooner one they've seen
        def keep(square: Square) -> float:
            index = view.positions[self.me].index(square)
            seen = view.tiles_on_board_revealed[self.me][index]
            tile = view.tiles_on_board[self.me][index]
            return self._tile_value(view, square, tile) - (1 if seen else 0)

        return min(possible_squares, key=keep)

    async def choose_smite_target(self, targets: list[Square]) -> Square:
        await self._pause()
        if self.level == "easy":
            return self.rng.choice(targets)
        view = self.view()
        ours = view.positions[self.me]

        def nearness(square: Square) -> float:
            return -min(abs(square.row - s.row) + abs(square.col - s.col) for s in ours)

        if self.level == "medium":
            return max(targets, key=nearness)
        # the piece most likely to hurt us, then the nearest
        chance = beliefs(view, self.me)

        def threat(square: Square) -> float:
            piece = view.piece_at(square)
            harmful = sum(chance[piece].get(t, 0.0) for t in HARMFUL)
            return harmful * 10 + nearness(square)

        return max(targets, key=threat)
