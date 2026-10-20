# Changeling

<img width="1745" alt="Screenshot 2025-04-23 at 12 00 02 PM" src="https://github.com/user-attachments/assets/f5f70296-d2aa-40e8-9586-ae10c61c189b" />

An original 2-player board game of strategy and deception.

## Rules

Players move tiles around the board to gain money and kill enemy tiles.  Each tile has a special ability, but tile identities are hidden from the opponent.

Each turn, each player chooses one of their tiles and chooses an ability for it to use, and the opponent can accept or challenge.

Each game uses 5 types of tiles, with 3 copies each.  The tile abilities are:
 - 🀥 FLOWER: move 1, gain $3
 - 🀨 HARVESTER: move forward 1, gain $4
 - 🀍 HOOK: grab an enemy along a straight or diagonal line, pull them adjacent, and steal $2.  Reflected by 🀍 HOOK.
 - 🀐 BIRD: move 2, gain $2, 🔎 REVEAL one tile unused this game
 - 🀛 GRENADES: roll a grenade exactly 2 squares away in an unobstructed cardinal direction, and explode a 3x3 square.
 - 🀒 KNIVES: pay $1 to kill at range 1, or $5 to kill at range 2.  Reflected by 🀒 KNIVES.
 - 🀌 THIEF: steal $4 at range 1, and swap places with target.  Reflected by 🀌 THIEF.
 - 🀙 FIREBALL: pay $3 to shoot a fireball along a straight or diagonal line, exploding 3x3 at impact. Direct hits reflected by FIREBALL.
 - 🀎 RAM: pay $3, move 1 cardinal direction, then knockback all adjacent tiles.  They die if they can't move.
 - 🀗 SPIDER: move 2, leaving webs where you went, then go again (at most two moves a turn).  An enemy crossing a web loses their next turn, and the web holds them until then; webs block fireballs, and fireballs and grenades clear them.
 - 🀩 FROST (experimental): pay $3 to kill every tile 2 squares away (the edge of the 5x5 square around it), your own too, and ice those squares.  A tile moving onto ice, for any reason, slides on the same way until it's off the ice or the next square is taken or off the board.  Fireballs and grenades melt ice (it doesn't block them).
 - 🀧 SUNBEAM (experimental): pay $1 to shine a beam straight up, down, left, or right to the edge, revealing every tile it crosses.  Reflected by 🀧 SUNBEAM, but only by the first tile it reaches.

After each action, opponents can:
 - ✓ ACCEPT: allow the claimed ability to proceed
 - 🚩 CHALLENGE: reveal the tile!
     - if it has the claimed ability, the challenger loses a tile, and the action proceeds.
     - if it doesn't have the claimed ability, the current player loses a tile, and action is blocked.
 - REFLECT: certain abilities can be reflected by certain defending tiles.  This can also be challenged by the original player.

Instead of claiming an ability, players can always ↕ MOVE: move 1 square, gain $1.

When a player reaches $10 coins, they immediately ⚡ SMITE: pay $10 to kill any enemy tile.

When a tile is killed, the owning player replaces it with a tile from their hand, if they have any.  When a player's 4th tile is killed, they lose and the game is over.

There are two types of special board locations:
 - EXCHANGE squares have two face-down tiles.  When a player moves onto them, they look at the face-down tiles and optionally exchange one with their current tile.
 - If a player starts their turn occupying the BONUS square, they get bonus money and 🔎 reveal tile(s) unused this game.

The table can play the starter set (fireball, harvester, hook, knives, bird), a custom pick, or a random one.  In randomized mode, the set of starting tiles is randomized, along with the effect of the bonus square and the smite cost.

## Implementation

A python backend and plain javascript frontend communicate over websockets.

Unlike a standard game loop, the state transitions are represented directly in code (see `_play_one_turn` in server/game.py) because the action sequences are all conditional on the sequence of challenges and responses.
