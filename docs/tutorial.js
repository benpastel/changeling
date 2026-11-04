"use strict";

// The tutorial: the first time this browser plays, a few steps over the live board
// show the gist, with the match paused for both players, and the same for the
// exchanges and the bonus square the first time a game has them (the simple board
// doesn't); after that, a tip the first time each other thing comes up.  Both are notes
// from the guide (see guide.js).
//
// Each step and tip finds what it points at in `game`: {board, view, highlight,
// selection, me, them}, the latest of what main.js has drawn.

import {RESPONSES} from "./constants.js";
import {dealLeft} from "./animate.js";

const KEY = "arena.tutorial";

const all = (selector) => () => [...document.querySelectorAll(selector)];
const one = (selector) => () => [document.querySelector(selector)].filter(Boolean);

const pieces = (side) => all(`.board .cell.${side} .piece`);
const myHand = one(".strip.bottom .hand");
const panel = one(".board .choice-panel");
const panelHas = (name) => document.querySelector(`.board .choice-panel .option[data-name="${name}"]`);

// the steps over the board, before the first move
const INTRO = [
  {
    text: (game) => `<b>You're ${game.me}, they're ${game.them}.</b> Each side has four tiles: two on the board, two in hand, hidden from the other side. Lose all four and you lose.`,
    point: (game) => pieces(game.me),
    spots: (game) => () => [...pieces(game.me)(), ...myHand()],
  },
  {
    text: "On your turn, pick a tile and <b>claim any ability</b>, even one it doesn't have. Or just move.<br><br>Right-click any tile to see what it does.",
    point: (game) => () => pieces(game.me)().slice(0, 1),
  },
  {
    text: "When they claim, you can accept, or <b>challenge</b> and reveal the tile. Whoever's wrong loses a tile.",
    point: (game) => pieces(game.them),
  },
];

// the full board's squares, the first time a game has them
const SQUARES = [
  {
    text: "An <b>exchange</b>: move onto one to look at its two hidden tiles, and swap yours for one if you like.",
    point: () => all(".board .cell.exchange"),
  },
  {
    text: (game) => {
      const {bonus_amount: amount, bonus_reveal: reveal} = game.view;
      const seen = reveal === 1 ? "a look at an unused tile" : `a look at ${reveal} unused tiles`;
      return `Start a turn on the <b>bonus</b> square for $${amount}${reveal ? ` and ${seen}` : ""}.`;
    },
    point: () => all(".board .cell.bonus"),
  },
];

// the tips, the first time each comes up; the first that's come up, of those not yet
// seen.  A panel already says what it's asking, so a tip about one only adds what it doesn't.
const TIPS = [
  {
    id: "reflected",
    // they've answered our claim by reflecting it
    when: (game) => game.selection?.reflect && panelHas("🚩"),
    text: () => "They reflected it. A reflect is a claim too, so you can challenge it.",
    point: () => panel,
  },
  {
    id: "reflect",
    when: () => [...document.querySelectorAll(".board .choice-panel .option")]
      .some((option) => option.dataset.pick === "button" && !(option.dataset.name in RESPONSES)),
    text: () => "You can <b>reflect</b>: claim a tile that turns this back on them. They can challenge that too.",
    point: () => () => [...document.querySelectorAll(".board .choice-panel .option")]
      .filter((option) => !(option.dataset.name in RESPONSES)),
  },
  {
    id: "answer",
    when: () => panelHas("🚩"),
    text: () => "Tiles you haven't seen. If none of what they claimed is here, it's a bluff.",
    point: () => one(".hidden-tiles-contents"),
  },
  {
    id: "unused",
    when: () => document.querySelector(".unused-contents .acc-tile:not(.back)"),
    text: () => "Tiles dealt to nobody this game.",
    point: () => one(".unused-contents"),
  },
  {
    id: "smite",
    when: (game) => Object.values(game.view.coins).some((coins) => coins >= game.view.smite_cost - 3),
    text: (game) => `At $${game.view.smite_cost}, a player <b>smites</b>: pays $${game.view.smite_cost} to kill any tile.`,
    point: (game) => {
      const [side] = Object.entries(game.view.coins).sort(([, a], [, b]) => b - a)[0];
      return one(`.strip.${side} .amount`);
    },
  },
  {
    id: "web",
    when: () => document.querySelector('.board .cell[data-terrain="▦"]'),
    text: () => "A <b>web</b>: an enemy crossing it loses their next turn.",
    point: () => all('.board .cell[data-terrain="▦"]'),
  },
  {
    id: "ice",
    when: () => document.querySelector('.board .cell[data-terrain="❄"]'),
    text: () => "<b>Ice</b>: anything moving onto it slides straight on until something stops it.",
    point: () => all('.board .cell[data-terrain="❄"]'),
  },
];

// what's been shown: the intro, the full board's squares, which tips; and whether tips
// are off.  Tips turned off before the squares had steps of their own leave them off too.
function load() {
  let saved = {};
  try {
    saved = JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
  } catch {
    // shown again
  }
  return {intro: false, board: saved.off ?? false, seen: [], off: false, ...saved};
}

// `guide` shows the notes; `pause(on)` pauses or resumes the match; `game()` gives what's
// on the board now, or null when there's no game showing
function setUpTutorial(guide, pause, game) {
  let saved = load();
  const save = () => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(saved));
    } catch {
      // private windows may refuse; it'll show again next time
    }
  };
  // the steps showing now, one after another, and which of them is, or null; and
  // whether we've paused the match
  let steps = null;
  let step = null;
  let waiting = 0;
  let paused = false;
  let tip = null;

  const setPaused = (on) => {
    paused = on;
    pause(on);
  };

  // the steps due before play, given the game: the intro, and the squares on a board
  // that has them
  const due = (view) => [
    ...(saved.intro ? [] : INTRO),
    ...(saved.board || view.exchange_positions.length === 0 ? [] : SQUARES),
  ];

  // through the steps, or out of them: either way they've been seen
  const end = () => {
    saved.intro ||= steps.includes(INTRO[0]);
    saved.board ||= steps.includes(SQUARES[0]);
    steps = null;
    step = null;
    save();
    guide.hide();
    setPaused(false);
    update();
  };

  const showStep = () => {
    const now = game();
    const {text, point, spots} = steps[step];
    const last = step === steps.length - 1;
    guide.show({
      text: typeof text === "function" ? text(now) : text,
      point: point(now),
      spots: spots ? spots(now) : undefined,
      dim: true,
      count: steps.length > 1 ? `${step + 1}/${steps.length}` : null,
      back: step > 0 ? ["back", () => {
        step -= 1;
        showStep();
      }] : null,
      secondary: ["end tutorial", end],
      primary: [last ? "play" : "next", () => {
        if (last) {
          end();
        } else {
          step += 1;
          showStep();
        }
      }],
    });
  };

  const showTip = (found, now) => {
    tip = found.id;
    const done = () => {
      tip = null;
      saved.seen = [...new Set([...saved.seen, found.id])];
      save();
      guide.hide();
      update();
    };
    guide.show({
      text: found.text(now),
      point: found.point(now),
      // never over the choice the game is asking for
      avoid: panel,
      secondary: ["no more tips", () => {
        saved.off = true;
        done();
      }],
      primary: ["got it", done],
      // gone once it's been dealt with, e.g. the claim it was about has been answered
      holds: () => Boolean(game()?.view && found.when(game())),
      gone: done,
    });
  };

  // look again at the game, after anything's been drawn
  function update() {
    const now = game();
    if (!now?.view) {
      if (tip) {
        tip = null;
        guide.hide();
      }
      return;
    }
    if (steps) {
      return;
    }
    const coming = due(now.view);
    if (coming.length) {
      tip = null;
      if (!paused) {
        setPaused(true);
      }
      // once the tiles are dealt, so the steps show where they've landed
      if (dealLeft() > 0) {
        window.clearTimeout(waiting);
        waiting = window.setTimeout(update, dealLeft() + 50);
        return;
      }
      steps = coming;
      step = 0;
      showStep();
      return;
    }
    if (saved.off || tip) {
      return;
    }
    const found = TIPS.find((t) => !saved.seen.includes(t.id) && t.when(now));
    if (found) {
      showTip(found, now);
    }
  }

  return {
    update,
    // a match started on `board`: pause it straight away if steps are to come, before
    // anyone can move
    started(board) {
      if (!saved.intro || (board === "full" && !saved.board)) {
        setPaused(true);
      }
    },
    // the server forgets our pause when we drop, so a reconnect asks again
    reconnected() {
      if (paused) {
        pause(true);
      }
    },
    get on() {
      return !saved.intro || !saved.board || !saved.off;
    },
    // from the settings: all over again, from the next thing drawn, or never
    set on(on) {
      saved = on
        ? {intro: false, board: false, seen: [], off: false}
        : {...saved, intro: true, board: true, off: true};
      save();
    },
  };
}

export {setUpTutorial, INTRO, SQUARES, TIPS};
