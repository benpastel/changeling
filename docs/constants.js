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
  "🀩": "🀩", // frost
  "🀧": "🀧", // sunbeam
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
  ["🀛", "GRENADES"],
  ["🀍", "HOOK"],
  ["🀎", "RAM"],
  ["🀩", "FROST"],
  ["🀧", "SUNBEAM"],
  ["🀗", "SPIDER"],
];
// still played by the server, but not offered at the table for now
const HELD_BACK = [
  ["🀇", "BACKSTABBER"],
];
// squares a tile has changed: a spider's web, and frost's ice
const WEB = "▦";
const ICE = "❄";
// names shown under the action panel buttons
const ACTION_NAMES = {
  "↕": "MOVE",
  "⚡": "SMITE",
  ...Object.fromEntries(ALL_TILES),
  ...Object.fromEntries(HELD_BACK),
  "✓": "ACCEPT",
  "🚩": "CHALLENGE",
  [WEB]: "WEB",
  [ICE]: "ICE",
};
// mini boards for the reference, drawn from your side (forward is up).  Each square is
// a token:
//   .  empty           @  the acting tile        g  where it started (dashed)
//   o  it can move here    x  it can hit an enemy here    E  an enemy tile
//   ↖ ↑ ↗ ← → ↙ ↘  a tile pushed or pulled that way
// with suffixes  *  inside an explosion   W  a web   I  ice   L  in a sunbeam.  A board is its grid, or
// {grid, arrows, mine}, an arrow being [from row, from column, to row, to column];
// arrows are an enemy's being moved, or with `mine`, your own tile's.
const BOARDS = {
  step: [
    ". . . . .",
    ". o o o .",
    ". o @ o .",
    ". o o o .",
    ". . . . .",
  ],
  forward: [
    ". . . . .",
    ". . o . .",
    ". . @ . .",
    ". . . . .",
    ". . . . .",
  ],
  two: [
    ". . o . .",
    ". o o o .",
    "o o @ o o",
    ". o o o .",
    ". . o . .",
  ],
  adjacent: [
    ". . . . .",
    ". . x . .",
    ". x @ x .",
    ". . x . .",
    ". . . . .",
  ],
  twoAway: [
    ". . x . .",
    ". x . x .",
    "x . @ . x",
    ". x . x .",
    ". . x . .",
  ],
  around: [
    ". . . . .",
    ". x x x .",
    ". x @ x .",
    ". x x x .",
    ". . . . .",
  ],
  fireballHit: {
    grid: [
      ". . . . .",
      ". . * * *",
      ". . * E* *",
      ". . * * *",
      ". @ . . .",
    ],
    arrows: [[4, 1, 2, 3]],
  },
  // with nothing in the way, it explodes at the edge
  fireballEdge: {
    grid: [
      ". . . * *",
      ". . . * *",
      ". . . * *",
      ". . . . .",
      ". @ . . .",
    ],
    arrows: [[4, 1, 1, 4]],
  },
  behind: [
    ". . . . .",
    ". . . . .",
    ". . @ . .",
    "x x x x x",
    "x x x x x",
  ],
  grenade: [
    ". * * * .",
    ". * * E* .",
    "x . @ . x",
    ". . . . .",
    ". . x . .",
  ],
  hook: {
    grid: [
      ". . . . .",
      ". . . . .",
      ". . @ . .",
      ". . . . .",
      ". . . . .",
    ],
    arrows: [[2, 2, 0, 0], [2, 2, 0, 2], [2, 2, 0, 4], [2, 2, 2, 0], [2, 2, 2, 4], [2, 2, 4, 0], [2, 2, 4, 2], [2, 2, 4, 4]],
  },
  ram: [
    ". . . . .",
    ". ↖ ↑ ↗ .",
    ". ← @ → .",
    ". ↙ g ↘ .",
    ". . . . .",
  ],
  web: [
    ". . . . .",
    ". . @W . .",
    ". . W . .",
    ". . gW . .",
    ". . . . .",
  ],
  // an enemy crossing a web
  webbed: {
    grid: [
      ". . . . .",
      ". . . . .",
      "E W W . .",
      ". . . . .",
      ". . . . .",
    ],
    arrows: [[2, 0, 2, 3]],
  },
  freeze: [
    "xI xI xI xI xI",
    "xI . . . xI",
    "xI . @ . xI",
    "xI . . . xI",
    "xI xI xI xI xI",
  ],
  // lighting up a line, the enemy it reaches first and the one behind
  beam: [
    ". . EL . .",
    ". . EL . .",
    ". . L . .",
    ". . @L . .",
    ". . . . .",
  ],
  // a step onto ice, sliding on until off it
  slide: {
    grid: [
      ". . . . .",
      ". . . . .",
      "g I I I @",
      ". . . . .",
      ". . . . .",
    ],
    arrows: [[2, 0, 2, 4]],
    mine: true,
  },
  // or until the next square is taken
  slideBlocked: {
    grid: [
      ". . . . .",
      ". . . . .",
      "g I I @I E",
      ". . . . .",
      ". . . . .",
    ],
    arrows: [[2, 0, 2, 3]],
    mine: true,
  },
};

// what each tile, moving, smiting, and each answer to a claim does: its uses (or,
// with `then`, what its use leaves behind), and notes on what isn't a use (reflects,
// smiting being forced).  A use has a label, what
// it costs or gains (the smite's cost is this game's: "smite"), its effects, a line
// to each, and the boards that show it, captioned when there are several.  A note is
// [mark, text].
const REFLECTED = "↩";
const REFERENCE = {
  "🀥": {uses: [{label: "move", gain: 3, lines: ["move 1 in any direction"], boards: [BOARDS.step]}]},
  "🀨": {uses: [{label: "move", gain: 4, lines: ["move forward 1"], boards: [BOARDS.forward]}]},
  "🀐": {uses: [{label: "move", gain: 2, lines: ["move up to 2", "reveal 1 unused tile"], boards: [BOARDS.two]}]},
  "🀒": {
    uses: [
      {label: "adjacent", cost: 1, lines: ["kill an adjacent enemy"], boards: [BOARDS.adjacent]},
      {label: "2 away", cost: 5, lines: ["kill an enemy 2 away"], boards: [BOARDS.twoAway]},
    ],
    notes: [[REFLECTED, "reflected by knives"]],
  },
  "🀌": {
    uses: [{label: "steal", gain: 4, lines: ["steal from an adjacent enemy", "swap places with it"], boards: [BOARDS.around]}],
    notes: [[REFLECTED, "reflected by thief"]],
  },
  "🀙": {
    uses: [{
      label: "shoot",
      cost: 3,
      lines: ["shoot along a diagonal", "explode 3×3 on the first tile it meets", "or at the edge, if it meets none"],
      boards: [BOARDS.fireballHit, BOARDS.fireballEdge],
      captions: ["hits a tile", "or the edge"],
    }],
    notes: [[REFLECTED, "a direct hit is reflected by fireball"]],
  },
  "🀇": {
    uses: [
      {label: "kill", cost: 3, lines: ["kill an enemy anywhere behind you"], boards: [BOARDS.behind]},
      {label: "move", gain: 2, lines: ["move up to 2"], boards: [BOARDS.two]},
    ],
    notes: [[REFLECTED, "a kill is reflected by backstabber"]],
  },
  "🀛": {
    uses: [{
      label: "throw",
      cost: 3,
      lines: ["roll a grenade exactly 2 squares, along a clear straight line", "explode 3×3 where it lands"],
      boards: [BOARDS.grenade],
    }],
  },
  "🀍": {
    uses: [{
      label: "pull",
      gain: 2,
      lines: ["pull an enemy beside you, along a straight or diagonal line", "steal from it"],
      boards: [BOARDS.hook],
    }],
    notes: [[REFLECTED, "reflected by hook"]],
  },
  "🀎": {
    uses: [{
      label: "ram",
      cost: 3,
      lines: ["move 1 straight", "knock every adjacent tile back 1", "any that can't move die"],
      boards: [BOARDS.ram],
    }],
  },
  "🀗": {
    uses: [
      {
        label: "move",
        lines: ["move up to 2", "leave webs where you went", "go again afterward (max twice)"],
        boards: [BOARDS.web],
      },
      {
        label: "web",
        then: true,
        lines: [
          "an enemy crossing a web loses their next turn, held until then",
          "webs block fireballs; fireballs and grenades clear them",
        ],
        boards: [BOARDS.webbed],
      },
    ],
  },
  "🀩": {
    uses: [{
      label: "freeze",
      cost: 3,
      lines: ["kill every tile 2 away, yours too", "ice those squares"],
      boards: [BOARDS.freeze],
    }, {
      label: "ice",
      then: true,
      lines: [
        "a tile moving onto ice slides on the same way",
        "until it's off the ice, or the next square is taken or off the board",
        "fireballs and grenades melt it",
      ],
      boards: [BOARDS.slide, BOARDS.slideBlocked],
      captions: ["off the ice", "or blocked"],
    }],
  },
  "🀧": {
    uses: [{
      label: "shine",
      cost: 1,
      lines: ["reveal tiles in a straight line"],
      boards: [BOARDS.beam],
    }],
    notes: [[REFLECTED, "reflected by sunbeam"]],
  },
  // what's on a square, rather than a tile
  [WEB]: {
    uses: [{
      lines: [
        "laid by a spider",
        "an enemy crossing it loses their next turn, held until then",
        "blocks fireballs; fireballs and grenades clear it",
      ],
      boards: [BOARDS.webbed],
    }],
  },
  [ICE]: {
    uses: [{
      lines: [
        "left by frost",
        "a tile moving onto it slides on the same way",
        "until it's off the ice, or the next square is taken or off the board",
        "fireballs and grenades melt it",
      ],
      boards: [BOARDS.slide, BOARDS.slideBlocked],
      captions: ["off the ice", "or blocked"],
    }],
  },
  "↕": {uses: [{label: "move", gain: 1, lines: ["move 1 in any direction"], boards: [BOARDS.step]}]},
  "⚡": {
    uses: [{label: "smite", cost: "smite", lines: ["kill any enemy tile"]}],
    notes: [["⚡", "forced on reaching the smite cost"]],
  },
  "✓": {uses: [{lines: ["the claimed ability goes ahead"]}]},
  "🚩": {
    uses: [{
      lines: [
        "the tile is revealed",
        "if it has the ability: the challenger loses a tile, and the ability goes ahead",
        "if not: the claimer loses a tile, and the ability is blocked",
      ],
    }],
  },
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
  WEB,
  ICE,
  REFERENCE,
  TILES_PER_GAME,
};
