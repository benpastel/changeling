"use strict";

import {
  ROWS,
  COLUMNS,
  TILES,
  PLAYERS,
  NORTH_PLAYER,
  SOUTH_PLAYER,
  HIDDEN_TILE,
  EXCHANGE_MARK,
  ACTION_NAMES,
  REFERENCE,
  WEB,
  ICE,
} from "./constants.js";


function createBoard(board, mySide) {
  // a 5x5 grid of squares, each knowing its own row and column; whoever is south sees
  // it as stored, and north sees it turned around, so your own side is always at the bottom
  board.innerHTML = "";
  const flip = mySide === NORTH_PLAYER;
  for (let i = 0; i < ROWS; i++) {
    for (let j = 0; j < COLUMNS; j++) {
      const row = flip ? ROWS - 1 - i : i;
      const column = flip ? COLUMNS - 1 - j : j;
      const cellElement = document.createElement("div");
      cellElement.className = "cell";
      cellElement.dataset.row = row;
      cellElement.dataset.column = column;
      board.append(cellElement);
    }
  }
  return board;
}

function findCell(board, row, col) {
  return board.querySelector(`.cell[data-row="${row}"][data-column="${col}"]`);
}

function addSquareMarks(cell, kind, contents) {
  // a special square keeps its piece where every square has it, full size and centred,
  // and marks itself in the bottom corners: the bonus on the left, or the exchange
  // tiles one in each corner
  cell.classList.add('special', kind);
  const marks = document.createElement("div");
  marks.classList.add("cell-marks");
  for (const content of contents) {
    const element = document.createElement("span");
    element.textContent = content;
    if (content in TILES || content === HIDDEN_TILE) {
      element.dataset.tileName = content;
      element.classList.add('board-tile');
      if (kind === "exchange") {
        // the exchange's mark, face up or down
        const mark = document.createElement("span");
        mark.className = "exchange-mark";
        mark.innerHTML = EXCHANGE_MARK;
        element.append(mark);
      }
    } else {
      element.classList.add('bonus');
    }
    marks.append(element);
  }
  cell.append(marks);
}

function renderBoard(board, player_view) {
  // set board empty
  for (const cell of board.querySelectorAll(".cell")) {
    cell.innerHTML = "";
    cell.classList.remove(NORTH_PLAYER, SOUTH_PLAYER, 'board-tile', 'special', 'bonus', 'exchange');
  }

  // create the bonus square
  const [bonusRow, bonusCol] = player_view.bonus_position;
  const bonusCell = findCell(board, bonusRow, bonusCol);
  const bonusText = '$'.repeat(player_view.bonus_amount) + '🔎'.repeat(player_view.bonus_reveal)

  addSquareMarks(bonusCell, 'bonus', [bonusText]);

  // create the exchange tile squares
  for (let p = 0; p < player_view.exchange_positions.length; p++) {
    const [exchangeRow, exchangeCol] = player_view.exchange_positions[p];
    const exchangeCell = findCell(board, exchangeRow, exchangeCol);
    addSquareMarks(exchangeCell, 'exchange', player_view.exchange_tiles[p]);
  }

  // set player tiles
  for (const player of PLAYERS) {
    const tiles = player_view.tiles_on_board[player];
    const positions = player_view.positions[player];

    for (let t = 0; t < tiles.length; t++) {
      const char = tiles[t];
      const [row, col] = positions[t];
      const cell = findCell(board, row, col);

      const piece = document.createElement("span");
      piece.classList.add("piece");
      piece.textContent = char;
      if (cell.classList.contains("exchange")) {
        // on an exchange square the piece is one of the tiles to choose between
        piece.dataset.tileName = char;
        piece.classList.add('board-tile');
      }
      cell.prepend(piece);
      cell.classList.add(player);
    }
  }

  // a square whose tile just died, waiting for its player to fill it from their hand
  for (const [player, [row, col]] of Object.entries(player_view.vacant || {})) {
    const vacancy = document.createElement("span");
    vacancy.className = `vacancy ${player}`;
    findCell(board, row, col).prepend(vacancy);
  }
}

// how each kind of log event reads, after the name of the player it's about;
// must match python LogKind
const LOG_WORDS = {
  reflect: "reflects",
  reveal: "reveals",
  lit: "shows",
  lose: "loses",
  exchange: "may have exchanged",
  web: "caught in web",
  skip: "skips turn",
  again: "goes again",
  x2: "×2 →",
  win: "wins",
  draw: "draw",
};

function logItem(glyph, name) {
  // a glyph with its small name beside it
  const item = document.createElement("span");
  item.className = "log-item";
  const glyphElement = document.createElement("span");
  glyphElement.className = "log-glyph";
  glyphElement.textContent = glyph;
  const nameElement = document.createElement("span");
  nameElement.className = "log-name";
  nameElement.textContent = name;
  item.append(glyphElement, nameElement);
  return item;
}

function logEventItem(event) {
  switch (event.kind) {
    case "challenge":
      return logItem("🚩", ACTION_NAMES["🚩"]);
    case "smite":
      return logItem("⚡", "SMITE");
    case "bonus":
      return logItem("$" + "🔎".repeat(event.count), "BONUS");
    default:
      return event.action ? logItem(event.action, ACTION_NAMES[event.action]) : null;
  }
}

function renderLogEvent(turnElement, event, names, showName) {
  const who = document.createElement("span");
  who.className = "log-who";
  if (event.player && showName) {
    who.classList.add(event.player);
    who.textContent = names[event.player];
    who.title = names[event.player];
  }

  const what = document.createElement("span");
  what.className = "log-what";
  what.classList.toggle("cancelled", event.cancelled);
  if (event.kind in LOG_WORDS) {
    what.append(LOG_WORDS[event.kind]);
  }
  const item = logEventItem(event);
  if (item) {
    what.append(item);
  }

  const coins = document.createElement("span");
  coins.className = "log-coins";
  for (const player of PLAYERS) {
    const delta = event.coins[player];
    if (delta) {
      const element = document.createElement("span");
      element.className = player;
      element.textContent = `${delta > 0 ? "+" : "−"}$${Math.abs(delta)}`;
      coins.append(element);
    }
  }

  turnElement.append(who, what, coins);
}

function renderLog(panel, player_view) {
  // one block per turn; every turn but the latest is faded
  const turns = player_view.public_log.filter((turn) => turn.events.length > 0);
  const latest = turns.findLastIndex((turn) => turn.player !== null);

  const list = document.createElement("div");
  list.className = "log-list";
  turns.forEach((turn, t) => {
    const turnElement = document.createElement("div");
    turnElement.className = "log-turn";
    turnElement.classList.toggle("old", t < latest);
    let previous = null;
    for (const event of turn.events) {
      // a player's name shows once for a run of their events
      renderLogEvent(turnElement, event, player_view.names, event.player !== previous);
      previous = event.player;
    }
    list.append(turnElement);
  });

  panel.replaceChildren(list);
  // scroll the log down to the bottom, so the latest line is visible
  panel.scrollTop = panel.scrollHeight;
}

function renderHand(player_view) {
  // each player's strip: name, coins, and the tiles in hand
  for (const player of PLAYERS) {
    const strip = document.querySelector(`.strip.${player}`);
    if (!strip) {
      continue;
    }
    const coins = player_view.coins[player];
    strip.querySelector(".name").textContent = player_view.names[player];
    // debt reads like the log's losses: −$1
    strip.querySelector(".amount").textContent = coins < 0 ? `−$${-coins}` : `$${coins}`;

    // compare by contents, not just count: a rematch can deal a new hand with the
    // same number of tiles, and a length-only check would leave stale tiles (and
    // stale dataset.tileName) from the previous game in the DOM.
    const hand = player_view.tiles_in_hand[player];
    const panel = strip.querySelector(".hand-tiles");
    const currentTiles = Array.from(panel.children, (e) => e.dataset.tileName);
    const handChanged =
      hand.length !== currentTiles.length ||
      hand.some((tile, i) => tile !== currentTiles[i]);
    if (handChanged) {
      panel.innerHTML = "";
      for (const tile of hand) {
        const element = document.createElement("span");
        element.textContent = tile;
        element.dataset.tileName = tile;
        element.classList.add("hand-tile");
        panel.append(element);
      }
    }
  }
}

function renderTerrain(board, player_view) {
  // what's been left on the squares: each player's webs, and anyone's ice.  A square
  // says which, so hovering it explains (ice, if it's both)
  for (const cell of board.querySelectorAll(".cell")) {
    for (const terrain of cell.querySelectorAll(".web, .ice")) {
      terrain.remove();
    }
    delete cell.dataset.terrain;
  }
  const lay = (squares, className, glyph) => {
    for (const [r, c] of squares) {
      const cell = findCell(board, r, c);
      const terrain = document.createElement("div");
      terrain.className = className;
      cell.prepend(terrain);
      cell.dataset.terrain = glyph;
    }
  };
  for (const player of PLAYERS) {
    lay(player_view.webs[player], `web ${player}`, WEB);
  }
  lay(player_view.ice ?? [], "ice", ICE);
}

function renderOther(player_view) {
  // the left column: each tile its own element, so a dying tile can fly to its place in the graveyard
  for (const [selector, tiles] of [
    [".graveyard-contents", player_view.discard],
    [".unused-contents", player_view.unused_tiles],
  ]) {
    const contents = document.querySelector(selector);
    contents.innerHTML = "";
    for (const tile of tiles) {
      const element = document.createElement("span");
      element.className = "acc-tile";
      element.classList.toggle("back", tile === HIDDEN_TILE);
      element.textContent = tile;
      contents.append(element);
    }
  }
  // the tiles in play, and under each in its own column, its copies we haven't seen
  const inPlay = document.querySelector(".in-play");
  const unknown = document.querySelector(".hidden-tiles-contents");
  inPlay.replaceChildren();
  unknown.replaceChildren();
  for (const tile of player_view.tiles_in_game) {
    const glyph = document.createElement("span");
    glyph.textContent = tile;
    inPlay.append(glyph);
    const column = document.createElement("span");
    column.className = "unknown-column";
    for (const hidden of player_view.hidden_tiles) {
      if (hidden === tile) {
        const element = document.createElement("span");
        element.className = "acc-tile";
        element.textContent = tile;
        column.append(element);
      }
    }
    unknown.append(column);
  }
  document.querySelector(".smite-cost .cost").textContent = `= $${player_view.smite_cost}`;
}

// what a tile, moving, smiting, or an answer to a claim does (see REFERENCE), with
// each use's price written out: its cost (the smite's being this game's) or its gain
function ruleOf(glyph, player_view) {
  const {uses, notes = []} = REFERENCE[glyph];
  return {
    uses: uses.map((use) => {
      const cost = use.cost === "smite" ? player_view.smite_cost : use.cost;
      const price = cost !== undefined
        ? {kind: "cost", text: `$${cost}`}
        : use.gain !== undefined ? {kind: "gain", text: `+$${use.gain}`} : null;
      return {...use, price};
    }),
    notes,
  };
}

function element(tag, className, text) {
  const e = document.createElement(tag);
  e.className = className;
  if (text !== undefined) {
    e.textContent = text;
  }
  return e;
}

function renderRules(list, player_view, entries = [...player_view.tiles_in_game, "↕", "⚡"]) {
  // the reference: every tile in play, then moving and smiting, or a single one.  Each
  // is its glyph and name, then a row to a use, its words then its boards (which
  // illustrate the words, so they come after), then notes on what isn't a use
  list.innerHTML = "";
  // a single entry gets the panel to itself
  list.classList.toggle("single", entries.length === 1);
  // moving and smiting aren't a tile's, so any of your tiles stands in on their boards
  for (const glyph of entries) {
    const actor = glyph in TILES ? glyph : HIDDEN_TILE;
    const {uses, notes} = ruleOf(glyph, player_view);
    const rule = element("div", "rule");
    const head = element("div", "rule-head");
    head.append(element("span", "rule-glyph", glyph), element("span", "rule-name", ACTION_NAMES[glyph]));
    rule.append(head);
    for (const use of uses) {
      const row = element("div", "rule-use");
      const words = element("div", "rule-words");
      if (use.label || use.price) {
        const title = element("div", "rule-title");
        if (use.label) {
          title.append(element("span", "rule-label", use.label));
        }
        if (use.price) {
          title.append(element("span", `rule-price ${use.price.kind}`, use.price.text));
        }
        words.append(title);
      }
      // one bullet to an effect
      const text = element("ul", "rule-text");
      for (const line of use.lines) {
        text.append(element("li", "", line));
      }
      words.append(text);
      row.append(words);
      if (use.boards) {
        const boards = element("div", "rule-boards");
        use.boards.forEach((diagram, i) => {
          const figure = element("div", "rule-figure");
          figure.append(renderDiagram(diagram, actor));
          if (use.captions) {
            figure.append(element("div", "rule-caption", use.captions[i]));
          }
          boards.append(figure);
        });
        row.append(boards);
      }
      rule.append(row);
    }
    if (notes.length) {
      const footer = element("div", "rule-notes");
      for (const [mark, text] of notes) {
        const note = element("div", "rule-note");
        note.append(element("span", "rule-mark", mark), element("span", "", text));
        footer.append(note);
      }
      rule.append(footer);
    }
    list.append(rule);
  }
}

function renderDiagram(diagram, actor) {
  // a mini board from BOARDS: each square's token is its mark, then any suffixes;
  // a diagram is its grid, or {grid, arrows}
  const {grid, arrows = [], mine = false} = Array.isArray(diagram) ? {grid: diagram} : diagram;
  const board = document.createElement("div");
  board.className = "rule-board";
  for (const line of grid) {
    for (const token of line.split(" ")) {
      const square = document.createElement("div");
      square.className = "rule-square";
      if (token.includes("*")) square.classList.add("blast");
      if (token.includes("W")) square.classList.add("webbed");
      if (token.includes("I")) square.classList.add("iced");
      if (token.includes("L")) square.classList.add("lit");
      const mark = token.replace(/[*WIL]/g, "");
      const markElement = document.createElement("span");
      if (mark === "@") {
        markElement.className = "rule-tile you";
        markElement.textContent = actor;
      } else if (mark === "E") {
        markElement.className = "rule-tile them";
        markElement.textContent = HIDDEN_TILE;
      } else if (mark === "g") {
        markElement.className = "rule-start";
      } else if (mark === "o" || mark === "x" || mark === "-") {
        markElement.className = {o: "rule-dot you", x: "rule-dot them", "-": "rule-dot trail"}[mark];
      } else if (mark !== ".") {
        markElement.className = "rule-sign";
        markElement.textContent = mark;
      }
      square.append(markElement);
      board.append(square);
    }
  }
  if (arrows.length) {
    const drawn = renderArrows(arrows);
    drawn.classList.toggle("mine", mine);
    board.append(drawn);
  }
  return board;
}

function renderArrows(arrows) {
  // arrows over a mini board, in units of squares, each starting clear of the tile it
  // leaves and stopping short of the square it reaches
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "rule-arrows");
  svg.setAttribute("viewBox", "0 0 5 5");
  const head = document.createElementNS(svgNS, "marker");
  head.setAttribute("id", "rule-arrowhead");
  head.setAttribute("viewBox", "0 0 10 10");
  head.setAttribute("refX", "8");
  head.setAttribute("refY", "5");
  head.setAttribute("markerWidth", "5");
  head.setAttribute("markerHeight", "5");
  head.setAttribute("orient", "auto");
  const tip = document.createElementNS(svgNS, "path");
  tip.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  tip.setAttribute("fill", "currentColor");
  head.append(tip);
  const defs = document.createElementNS(svgNS, "defs");
  defs.append(head);
  svg.append(defs);
  for (const [fromRow, fromCol, toRow, toCol] of arrows) {
    const dx = toCol - fromCol;
    const dy = toRow - fromRow;
    const length = Math.hypot(dx, dy);
    const [ux, uy] = [dx / length, dy / length];
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", fromCol + 0.5 + ux * 0.45);
    line.setAttribute("y1", fromRow + 0.5 + uy * 0.45);
    line.setAttribute("x2", toCol + 0.5 - ux * 0.2);
    line.setAttribute("y2", toRow + 0.5 - uy * 0.2);
    line.setAttribute("marker-end", "url(#rule-arrowhead)");
    svg.append(line);
  }
  return svg;
}

export {createBoard, renderBoard, renderLog, renderHand, findCell, renderOther, renderRules, ruleOf, renderTerrain};
