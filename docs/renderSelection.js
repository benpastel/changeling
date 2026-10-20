"use strict";

// Draws the choices of a turn on the board.
//
//  - Once a piece is picked, every square it can reach shows a small glyph for each
//    ability that can target it; clicking one picks the ability and the target at once.
//  - A finished claim is a line from the piece to its target in the claimant's colour,
//    annotated with the claimed ability.  A reflect is added to the note; the answers
//    to a claim are offered beside it (see renderChoice.js).
//  - A target picked on its own (the tile a player is about to lose) is a pick.
//  - Hovering a blast or a ram's option ghosts what it would do: the blast's area
//    tinted, a cross on every tile that would die, an arrow on every tile knocked back.

import {
  CHOSEN_START,
  CHOSEN_TARGET,
  ALL_TILES,
  TILES,
} from "./constants.js";

import {findCell} from "./renderState.js";

const SVG = "http://www.w3.org/2000/svg";

// how far the claim's note sits off its line, as a fraction of the board's width
const NOTE_OFFSET = 0.025;


function pieceCenter(board, square) {
  const [row, col] = square;
  const cell = findCell(board, row, col).getBoundingClientRect();
  const origin = board.getBoundingClientRect();
  return [cell.left + cell.width / 2 - origin.left, cell.top + cell.height / 2 - origin.top];
}

function option(name) {
  // a clickable glyph for an ability or a response; tiles are their own glyph, and
  // the rest (↕ ⚡ ✓ 🚩) sit in a shell drawn to match a tile's frame
  const element = document.createElement("span");
  element.classList.add("option");
  element.dataset.name = name;
  if (!(name in TILES)) {
    element.classList.add("shell");
    const symbol = document.createElement("span");
    symbol.classList.add("symbol");
    const text = document.createElement("span");
    text.textContent = name;
    symbol.append(text);
    element.append(symbol);
  } else {
    element.textContent = name;
  }
  return element;
}

// options in a square are always in the same order: the tiles as listed, then ↕ last
const TILE_ORDER = ALL_TILES.map(([tile]) => tile);
function optionOrder(action) {
  const index = TILE_ORDER.indexOf(action);
  return index === -1 ? TILE_ORDER.length : index;
}

function drawTargets(board, targets, impacts, selection) {
  const bySquare = new Map();
  for (const [action, squares] of Object.entries(targets)) {
    for (const [row, col] of squares) {
      const key = `${row},${col}`;
      if (!bySquare.has(key)) {
        bySquare.set(key, {row, col, actions: []});
      }
      bySquare.get(key).actions.push(action);
    }
  }
  for (const {row, col, actions} of bySquare.values()) {
    const options = document.createElement("div");
    options.classList.add("cell-options");
    actions.sort((a, b) => optionOrder(a) - optionOrder(b));
    for (const action of actions) {
      const element = option(action);
      const impact = impacts[action]?.find(({target}) => target[0] === row && target[1] === col);
      const moves = selection.start && moving(board, selection.player, action, [row, col]);
      if (impact || moves) {
        // mouseover, not mouseenter, so it's drawn before the tooltip places itself
        // clear of it
        element.addEventListener("mouseover", () => {
          clearImpact(board);
          if (moves) {
            drawMove(board, selection.player, selection.start, [row, col]);
          }
          if (impact) {
            drawImpact(board, impact);
          }
        });
        element.addEventListener("mouseout", () => clearImpact(board));
      }
      options.append(element);
    }
    findCell(board, row, col).append(options);
  }
}

function svgElement(name, attributes) {
  const element = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, value);
  }
  return element;
}

function drawImpact(board, {area, killed, pushed}) {
  const svg = document.createElementNS(SVG, "svg");
  svg.classList.add("impact");
  const origin = board.getBoundingClientRect();
  const size = findCell(board, 0, 0).getBoundingClientRect().width;
  for (const [row, col] of area) {
    const cell = findCell(board, row, col).getBoundingClientRect();
    svg.append(svgElement("rect", {
      class: "impact-area",
      x: cell.left - origin.left, y: cell.top - origin.top,
      width: cell.width, height: cell.height,
    }));
  }
  // an arrow from the middle of each knocked tile, pointing where it goes
  for (const [from, to] of pushed) {
    const [x1, y1] = pieceCenter(board, from);
    const [x2, y2] = pieceCenter(board, to);
    const length = Math.hypot(x2 - x1, y2 - y1);
    const [ux, uy] = [(x2 - x1) / length, (y2 - y1) / length];
    const [sx, sy] = [x1 - ux * size * 0.15, y1 - uy * size * 0.15];
    const [ex, ey] = [x1 + ux * size * 0.42, y1 + uy * size * 0.42];
    const head = size * 0.16;
    const [bx, by] = [ex - ux * head, ey - uy * head];
    const [px, py] = [-uy * head * 0.6, ux * head * 0.6];
    const arrow = svgElement("g", {class: "impact-push"});
    arrow.append(
      svgElement("line", {x1: sx, y1: sy, x2: bx, y2: by}),
      svgElement("polygon", {points: `${ex},${ey} ${bx + px},${by + py} ${bx - px},${by - py}`}),
    );
    svg.append(arrow);
  }
  // a cross on each tile that would die
  for (const square of killed) {
    const [x, y] = pieceCenter(board, square);
    const arm = size * 0.22;
    for (const kind of ["impact-halo", "impact-kill"]) {
      for (const [dx, dy] of [[arm, arm], [arm, -arm]]) {
        svg.append(svgElement("line", {
          class: kind, x1: x - dx, y1: y - dy, x2: x + dx, y2: y + dy,
        }));
      }
    }
  }
  board.append(svg);
}

function clearImpact(board) {
  for (const element of board.querySelectorAll(".impact")) {
    element.remove();
  }
}

function arrowhead(x, y, ux, uy, head) {
  const [bx, by] = [x - ux * head, y - uy * head];
  const [px, py] = [-uy * head * 0.55, ux * head * 0.55];
  return svgElement("polygon", {points: `${x},${y} ${bx + px},${by + py} ${bx - px},${by - py}`});
}

// the claim line a move would draw, ghosted, from the piece to where it would go
function drawMove(board, player, start, target) {
  const [x1, y1] = pieceCenter(board, start);
  const [x2, y2] = pieceCenter(board, target);
  const length = Math.hypot(x2 - x1, y2 - y1);
  const [ux, uy] = [(x2 - x1) / length, (y2 - y1) / length];
  const head = board.getBoundingClientRect().width * 0.04;
  const svg = document.createElementNS(SVG, "svg");
  svg.classList.add("claim-line", "impact", "ghost-move", player);
  svg.append(
    svgElement("line", {x1, y1, x2: x2 - ux * head * 0.8, y2: y2 - uy * head * 0.8}),
    arrowhead(x2, y2, ux, uy, head),
  );
  board.append(svg);
}

function drawClaim(board, selection) {
  const {player, start, action, target, reflect} = selection;
  const [x1, y1] = pieceCenter(board, start);
  const [x2, y2] = pieceCenter(board, target);
  const width = board.getBoundingClientRect().width;

  // the note sits beside the middle of the line, on its upper (or right) side, running
  // away from the line; with no line (a claim on its own square) it sits above the piece
  let noteX = (x1 + x2) / 2;
  let noteY = (y1 + y2) / 2;
  let anchor = "above";
  const length = Math.hypot(x2 - x1, y2 - y1);
  if (length > 0) {
    const svg = document.createElementNS(SVG, "svg");
    svg.classList.add("claim-line", player);
    // the end says what the claim does there: an arrowhead where the piece moves to,
    // a cross where it attacks
    const [ux, uy] = [(x2 - x1) / length, (y2 - y1) / length];
    const attack = isAttack(board, selection);
    const head = width * 0.04;
    const line = document.createElementNS(SVG, "line");
    line.setAttribute("x1", x1);
    line.setAttribute("y1", y1);
    line.setAttribute("x2", attack ? x2 : x2 - ux * head * 0.8);
    line.setAttribute("y2", attack ? y2 : y2 - uy * head * 0.8);
    svg.append(line);
    if (attack) {
      const arm = width * 0.02;
      for (const halo of [true, false]) {
        for (const [dx, dy] of [[arm, arm], [arm, -arm]]) {
          const stroke = document.createElementNS(SVG, "line");
          stroke.setAttribute("x1", x2 - dx);
          stroke.setAttribute("y1", y2 - dy);
          stroke.setAttribute("x2", x2 + dx);
          stroke.setAttribute("y2", y2 + dy);
          stroke.classList.add(halo ? "claim-halo" : "claim-cross");
          svg.append(stroke);
        }
      }
    } else {
      svg.append(arrowhead(x2, y2, ux, uy, head));
    }
    board.append(svg);

    let [nx, ny] = [-(y2 - y1) / length, (x2 - x1) / length];
    if (ny > 0 || (ny === 0 && nx < 0)) {
      [nx, ny] = [-nx, -ny];
    }
    noteX += nx * width * NOTE_OFFSET;
    noteY += ny * width * NOTE_OFFSET;
    if (Math.abs(nx) > 2 * Math.abs(ny)) {
      anchor = nx > 0 ? "right" : "left";
    } else if (Math.abs(nx) * 2 > Math.abs(ny)) {
      // beside a slanted line, the note hangs from its corner so it stays clear of it
      anchor = nx > 0 ? "above-right" : "above-left";
    }
  } else {
    noteY -= width * 0.08;
  }

  const note = document.createElement("div");
  note.classList.add("claim-note", anchor);
  note.style.left = `${noteX}px`;
  note.style.top = `${noteY}px`;

  const claimed = document.createElement("span");
  claimed.classList.add("claimed", player);
  claimed.textContent = action;
  note.append(claimed);

  if (reflect) {
    const reflected = document.createElement("span");
    reflected.classList.add("claimed", player === "north" ? "south" : "north");
    reflected.textContent = reflect;
    note.append(reflected);
  }

  board.append(note);
  keepOnBoard(board, note, noteX, noteY, x1, y1, x2, y2);
}

// abilities whose target is something attacked, rather than a square moved to
const ATTACKS = new Set(["🀒", "🀌", "🀙", "🀛", "🀍"]);

// whether an ability takes the piece to its target (a smite stays put)
function moving(board, player, action, target) {
  return Boolean(player) && action !== "⚡" && !isAttack(board, {player, action, target});
}

function isAttack(board, {player, action, target}) {
  // a backstabber kills an enemy behind it, but otherwise moves
  if (action === "🀇") {
    const [row, col] = target;
    const enemy = player === "north" ? "south" : "north";
    return findCell(board, row, col).classList.contains(enemy);
  }
  return ATTACKS.has(action);
}

function keepOnBoard(board, note, noteX, noteY, x1, y1, x2, y2) {
  // a note that would run off the board goes on the other side of its line instead
  const bounds = board.getBoundingClientRect();
  const rect = note.getBoundingClientRect();
  const flips = {
    right: "left", left: "right", above: "below",
    "above-right": "below-left", "above-left": "below-right",
  };
  const off =
    rect.left < bounds.left || rect.right > bounds.right ||
    rect.top < bounds.top || rect.bottom > bounds.bottom;
  const anchor = Object.keys(flips).find((a) => note.classList.contains(a));
  if (!off || !anchor) {
    return;
  }
  // mirror the note's point through the line's middle
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;
  note.classList.replace(anchor, flips[anchor]);
  note.style.left = `${2 * midX - noteX}px`;
  note.style.top = `${anchor === "above" && x1 === x2 && y1 === y2 ? midY + (midY - noteY) : 2 * midY - noteY}px`;
}

function clearSelection(board) {
  for (const element of board.querySelectorAll(`.${CHOSEN_START}, .${CHOSEN_TARGET}`)) {
    element.classList.remove(CHOSEN_START, CHOSEN_TARGET);
  }
  for (const element of board.querySelectorAll(".claim-line, .claim-note, .cell-options, .impact")) {
    element.remove();
  }
}

function renderSelection(board, selection, highlight) {
  clearSelection(board);
  const targets = highlight?.targets ?? {};

  if (selection && selection.start && selection.action && selection.target) {
    drawClaim(board, selection);
    return;
  }

  if (selection?.start) {
    const [row, col] = selection.start;
    findCell(board, row, col).classList.add(CHOSEN_START);
  }
  if (selection?.target) {
    const [row, col] = selection.target;
    findCell(board, row, col).classList.add(CHOSEN_TARGET);
  }
  drawTargets(board, targets, highlight?.impacts ?? {}, selection ?? {});
}

export {renderSelection, option};
