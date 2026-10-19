"use strict";

// must match python state and CSS sizing assumptions
const ROWS = 5;
const COLUMNS = 5;

// must match css classes and python enums
const NORTH_PLAYER = "north";
const SOUTH_PLAYER = "south";
const PLAYERS = [NORTH_PLAYER, SOUTH_PLAYER];

// must match css classes
const HIGHLIGHT = "highlight"; // squares, actions, or tiles the player can select right now
const CHOSEN_START = "chosen-start"; // the piece picked mid-turn
const CHOSEN_TARGET = "chosen-target"; // a square picked on its own, e.g. the tile to lose

const TILES = {
  "🀥": "🀥", // flower
  "🀐": "🀐", // bird
  "🀛": "🀛", // grenades
  "🀒": "🀒", // knives
  "🀍": "🀍", // hook
  "🀨": "🀨", // harvester
  "🀗": "🀗", // spider
  "🀇": "🀇", // backstabber
  "🀙": "🀙", // fireball
  "🀩": "🀩", // trickster
  "🀎": "🀎", // ram
  "🀌": "🀌", // thief
};
const HIDDEN_TILE = "🀫";

// the mark of a tile on an exchange: turning arrows in a fine ring, drawn in the
// corner of the exchange's tiles and of the tray's copies known to be on one
const EXCHANGE_MARK =
  '<svg viewBox="0 0 24 24" aria-hidden="true">' +
  '<circle cx="12" cy="12" r="11" style="fill: var(--surface); stroke: var(--ink)" stroke-width="1" />' +
  '<g transform="translate(12 12) scale(0.8) translate(-12 -12)">' +
  '<g fill="none" style="stroke: var(--ink)" stroke-width="1.9" stroke-linecap="round">' +
  '<path d="M5.34 10.21A6.9 6.9 0 0 1 15.96 6.35" /><path d="M18.66 13.79A6.9 6.9 0 0 1 8.04 17.65" />' +
  '</g><g style="fill: var(--ink)">' +
  '<path d="M18.74 8.30L17.01 1.71L11.96 8.92Z" /><path d="M5.26 15.70L6.99 22.29L12.04 15.08Z" />' +
  '</g></g></svg>';

// every tile that can be chosen for a game, in order; must match python ALL_TILES
const ALL_TILES = [
  ["🀥", "FLOWER"],
  ["🀨", "HARVESTER"],
  ["🀐", "BIRD"],
  ["🀒", "KNIVES"],
  ["🀌", "THIEF"],
  ["🀙", "FIREBALL"],
  ["🀇", "BACKSTABBER"],
  ["🀛", "GRENADES"],
  ["🀍", "HOOK"],
  ["🀎", "RAM"],
  ["🀩", "TRICKSTER"],
  ["🀗", "SPIDER"],
];
// names shown under the action panel buttons
const ACTION_NAMES = {
  "↕": "MOVE",
  "⚡": "SMITE",
  ...Object.fromEntries(ALL_TILES),
  "✓": "ACCEPT",
  "🚩": "CHALLENGE",
};
// what each tile does, for the reference, one effect per line; the smite's cost varies
// per game and is filled in where it's shown
const DESCRIPTIONS = {
  "🀥": ["move 1 in any direction", "gain $3"],
  "🀨": ["move forward 1", "gain $4"],
  "🀐": ["move up to 2", "gain $2", "reveal 1 unused tile"],
  "🀒": ["kill an adjacent enemy for $1", "or an enemy 2 away for $5", "reflected by knives"],
  "🀌": ["steal $4 from an adjacent enemy, swapping places with it", "reflected by thief"],
  "🀙": ["pay $3 to shoot along a diagonal", "explodes 3×3 where it hits", "a direct hit is reflected by fireball"],
  "🀇": ["pay $3 to kill the tile behind you", "reflected by backstabber", "or move 2 and gain $2"],
  "🀛": ["pay $3 to roll a grenade exactly 2 squares", "along a clear straight line", "explodes 3×3 where it lands"],
  "🀍": ["pull an enemy beside you, along a straight or diagonal line", "steal $2 from it", "reflected by hook"],
  "🀎": ["pay $3 to move 1 straight", "knock every adjacent tile back 1", "any that can't move die"],
  "🀩": ["move like a knight", "gain $1", "landing on an enemy swaps your identities", "then bumps it to a random adjacent square"],
  "🀗": [
    "move 2",
    "leave webs behind",
    "an enemy crossing a web loses a turn",
    "webs block fireballs",
    "fireballs and grenades clear webs",
    "go again after an exchange",
  ],
  "↕": ["move 1", "gain $1"],
  "⚡": ["on reaching the smite cost", "pay it to kill any enemy tile"],
  "✓": ["the claimed ability goes ahead"],
  "🚩": [
    "the tile is revealed",
    "if it has the ability: the challenger loses a tile, and the ability goes ahead",
    "if not: the claimer loses a tile, and the ability is blocked",
  ],
};
// a mini board for each, drawn from your side (forward is up); a tile with two uses
// gets one board per use. Each square is a token:
//   .  empty           @  the acting tile        g  where it started (dashed)
//   o  it can move here    x  it can hit an enemy here    E  an enemy tile
//   1 5  knives' cost at that range    -  the fireball's flight
//   ↖ ↑ ↗ ← → ↙ ↘  a tile pushed or pulled that way
// with suffixes  *  inside an explosion   W  a web
const DIAGRAMS = {
  "↕": [[
    ". . . . .",
    ". o o o .",
    ". o @ o .",
    ". o o o .",
    ". . . . .",
  ]],
  "🀥": [[
    ". . . . .",
    ". o o o .",
    ". o @ o .",
    ". o o o .",
    ". . . . .",
  ]],
  "🀨": [[
    ". . . . .",
    ". . o . .",
    ". . @ . .",
    ". . . . .",
    ". . . . .",
  ]],
  "🀐": [[
    ". . o . .",
    ". o o o .",
    "o o @ o o",
    ". o o o .",
    ". . o . .",
  ]],
  "🀒": [[
    ". . 5 . .",
    ". 5 1 5 .",
    "5 1 @ 1 5",
    ". 5 1 5 .",
    ". . 5 . .",
  ]],
  "🀌": [[
    ". . . . .",
    ". x x x .",
    ". x @ x .",
    ". x x x .",
    ". . . . .",
  ]],
  // an arrow is [from row, from column, to row, to column]
  "🀙": [{
    grid: [
      ". . . . .",
      ". . * * *",
      ". . * E* *",
      ". . * * *",
      ". @ . . .",
    ],
    arrows: [[4, 1, 2, 3]],
  }, {
    // with nothing in the way, it explodes at the edge
    grid: [
      ". . . * *",
      ". . . * *",
      ". . . * *",
      ". . . . .",
      ". @ . . .",
    ],
    arrows: [[4, 1, 1, 4]],
  }],
  "🀇": [[
    ". . . . .",
    ". . . . .",
    ". . @ . .",
    "x x x x x",
    "x x x x x",
  ], [
    ". . o . .",
    ". o o o .",
    "o o @ o o",
    ". o o o .",
    ". . o . .",
  ]],
  "🀛": [[
    ". * * * .",
    ". * * E* .",
    "x . @ . x",
    ". . . . .",
    ". . x . .",
  ]],
  "🀍": [{
    grid: [
      ". . . . .",
      ". . . . .",
      ". . @ . .",
      ". . . . .",
      ". . . . .",
    ],
    arrows: [[2, 2, 0, 0], [2, 2, 0, 2], [2, 2, 0, 4], [2, 2, 2, 0], [2, 2, 2, 4], [2, 2, 4, 0], [2, 2, 4, 2], [2, 2, 4, 4]],
  }],
  "🀎": [[
    ". . . . .",
    ". ↖ ↑ ↗ .",
    ". ← @ → .",
    ". ↙ g ↘ .",
    ". . . . .",
  ]],
  "🀩": [[
    ". o . E .",
    "o . . . o",
    ". . @ . .",
    "o . . . o",
    ". o . o .",
  ]],
  "🀗": [[
    ". . . . .",
    ". . @W . .",
    ". . W . .",
    ". . gW . .",
    ". . . . .",
  ]],
};
// must match python TILES_PER_GAME
const TILES_PER_GAME = 5;
const OTHER_ACTIONS = {
  "↕": "↕", // move
};
const RESPONSES = {
  "✓": "✓", // accept
  "🚩": "🚩", // challenge
};

export {
  EXCHANGE_MARK,
  ROWS,
  COLUMNS,
  NORTH_PLAYER,
  SOUTH_PLAYER,
  PLAYERS,
  HIGHLIGHT,
  CHOSEN_START,
  CHOSEN_TARGET,
  TILES,
  OTHER_ACTIONS,
  RESPONSES,
  HIDDEN_TILE,
  ALL_TILES,
  ACTION_NAMES,
  DESCRIPTIONS,
  DIAGRAMS,
  TILES_PER_GAME,
};
