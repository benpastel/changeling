"""
Bot against bot, many games, to compare the levels: who wins, by how much, and how
often each lies and challenges.

    uv run python -m scripts.bot_tournament hard medium 200
"""

import asyncio
import random
import sys
import time
from collections import Counter

from server.agents import Agent
from server.bots import Bot
from server.constants import GameResult, Player
from server.game import play_one_game
from server.state import LogKind


async def play(north: str, south: str, games: int, seed: int) -> None:
    rng = random.Random(seed)
    random.seed(seed)
    wins: Counter = Counter()
    stats: dict[Player, Counter] = {p: Counter() for p in Player}
    before: dict[Player, Counter] = {p: Counter() for p in Player}
    bots: dict[Player, Bot] = {}
    kinds: dict[Player, Counter] = {p: Counter() for p in Player}
    turns = 0
    began = time.monotonic()
    for game in range(games):
        # a match is ten games, with the same bots throughout, as at a table
        if game % 10 == 0:
            bots = {
                Player.N: Bot(north, delay=0, rng=rng),
                Player.S: Bot(south, delay=0, rng=rng),
            }
            for player in Player:
                stats[player] += before[player]
            before = {p: Counter() for p in Player}
        agents: dict[Player, Agent] = {p: b for p, b in bots.items()}
        first = Player.S if game % 2 == 0 else Player.N
        names = {Player.N: north, Player.S: south}
        try:
            _, result = await asyncio.wait_for(
                play_one_game(
                    {p: 0 for p in Player}, agents, None, first, names, "unlimited"
                ),
                timeout=30,
            )
        except TimeoutError:
            state = bots[Player.N]._state
            assert state is not None
            print(f"game {game} stuck after {len(state.public_log)} turns")
            print(state.public_log[-3:], state.positions, state.coins)
            raise
        wins[result] += 1
        state = bots[Player.N]._state
        assert state is not None
        turns += len(state.public_log)
        for player in Player:
            # the bots' counts run over the match; keep the latest
            before[player] = Counter(bots[player].stats)
        for turn in state.public_log:
            for event in turn.events:
                if event.player is not None:
                    kinds[event.player][event.kind] += 1
            # a challenge is right when the revealed tile isn't the one claimed
            claimed = None
            for event in turn.events:
                if event.kind in (LogKind.CLAIM, LogKind.REFLECT):
                    claimed = event.action
                elif event.kind == LogKind.CHALLENGE and event.player is not None:
                    challenger = event.player
                elif event.kind == LogKind.REVEAL:
                    right = event.action != claimed
                    stats[challenger][
                        "challenge right" if right else "challenge wrong"
                    ] += 1
    for player in Player:
        stats[player] += before[player]
    took = time.monotonic() - began
    print(
        f"north {north}: {wins[GameResult.NORTH_WINS]}  "
        f"south {south}: {wins[GameResult.SOUTH_WINS]}  "
        f"draws: {wins[GameResult.DRAW]}  "
        f"({turns / games:.0f} turns a game, {took / games * 1000:.0f}ms a game)"
    )
    for player, level in ((Player.N, north), (Player.S, south)):
        k, s = kinds[player], stats[player]
        challenges = s["challenge right"] + s["challenge wrong"]
        claims = s["true claim"] + s["lie"]
        print(
            f"  {level:>6}: per game {s['move'] / games:.1f} moves, "
            f"{s['true claim'] / games:.1f} true claims, {s['lie'] / games:.1f} lies "
            f"({s['lie'] / max(1, claims):.0%} of claims), "
            f"{challenges / games:.1f} challenges ({s['challenge right'] / max(1, challenges):.0%} right), "
            f"{k[LogKind.REFLECT] / games:.1f} reflects, {k[LogKind.SMITE] / games:.1f} smites"
        )


if __name__ == "__main__":
    north, south = sys.argv[1], sys.argv[2]
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 100
    asyncio.run(play(north, south, games, seed=1))
