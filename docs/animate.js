// Animates the change from one state to the next, so it's easier to see what happened:
//   - a piece slides to its new square
//   - a dying tile flies to its place in the graveyard, and a tile placed
//     from a hand flies onto the board, the rest of the hand closing up behind it
//   - an exchange swaps the tile with the one it takes, then shuffles its stack
//   - a tile that's revealed, or hidden again, turns over: on the board, on an
//     exchange, and everything at the end of the game; an unused tile seen with the
//     bonus turns over in the unused list
//   - money gained or spent floats up from the player's amount
//   - webs fade in and out
//   - a new game's tiles are dealt out from a pile in the middle of the board: to each
//     player's squares and hand, onto the exchanges, and the rest to the unused list
//
// Tiles clack as they land, fall and turn over (see sound.js).
//
// Call snapshot() before drawing the new state, and animate() after, with the new state.
//
// Ideas not yet tried: attacks drawn from attacker to target (a fireball's flight, the
// knives, the smite's bolt); the turn's highlight crossfading between the strips; the

import {PLAYERS, HIDDEN_TILE} from "./constants.js";
import {findCell} from "./renderState.js";
import {settings} from "./settings.js";
import {play} from "./sound.js";

// pieces slide at one speed however far they go: a step, a hook's pull, a ram's knockback
const SLIDE_MS_PER_SQUARE = 220;
// tiles flying on and off the board (to the graveyard, from a hand, to and from an
// exchange) go at one speed too, for now the slides', and however short the hop, take
// as long as two squares, so a tile placed from a hand next to it is still seen to
// arrive; a dying tile first pauses where it died
const FLY_MS_PER_SQUARE = 220;
const FLY_MIN_SQUARES = 2;
const PAUSE_MS = 140;
// the pause between an exchange's swap and the shuffle of its stack
const SHUFFLE_BEAT_MS = 250;
const FLIP_MS = 420;
const FADE_MS = 300;
const FLOAT_MS = 1100;
// the deal: a tile leaves the pile this often, and takes this long to arrive
const DEAL_GAP_MS = 55;
const DEAL_FLY_MS = 260;

let lastView = null;

// where everything was drawn before the new state replaces it
function snapshot(board) {
  if (!lastView) {
    return null;
  }
  const pieces = {};
  const hands = {};
  for (const player of PLAYERS) {
    pieces[player] = lastView.positions[player].map(([row, col], index) => {
      const piece = pieceAt(board, row, col);
      if (!piece) {
        return null;
      }
      const style = getComputedStyle(piece);
      return {
        rect: piece.getBoundingClientRect(),
        glyph: lastView.tiles_on_board[player][index],
        color: style.color,
        fontSize: style.fontSize,
      };
    });
    hands[player] = Array.from(
      document.querySelectorAll(`.strip.${player} .hand-tile`),
      (tile) => ({glyph: tile.textContent, rect: tile.getBoundingClientRect()}),
    );
  }
  const marks = lastView.exchange_positions.map(([row, col]) =>
    Array.from(exchangeMarks(board, row, col), (mark) => mark.getBoundingClientRect()),
  );
  return {view: lastView, pieces, hands, marks};
}

// a game no one has done anything in yet
const fresh = (view) => view.public_log.every((turn) => turn.events.length === 0);

// the deal's animations, until they're done or something happens; and when it began
let dealing = [];
let dealt = 0;

function animate(before, board, view) {
  const previous = lastView;
  lastView = view;
  if (fresh(view)) {
    if (!(previous && fresh(previous))) {
      dealing = [];
      dealt = performance.now();
      if (settings.deal) {
        deal(board, view, true);
      } else {
        play("start");
      }
    } else if (dealing.length) {
      // drawn again before anything's happened: what's still to arrive stays hidden
      deal(board, view, false);
    }
    return;
  }
  // something's happened, and is drawn where it is, so the deal ends where it's got to
  for (const animation of dealing) {
    animation.finish();
  }
  dealing = [];
  if (!before || before.view !== previous) {
    return;
  }

  // a new game deals new hands and empties the graveyard: nothing to animate
  const was = before.view;
  if (
    view.discard.length < was.discard.length ||
    PLAYERS.some((p) => view.tiles_in_hand[p].length > was.tiles_in_hand[p].length)
  ) {
    return;
  }

  const square = board.querySelector(".cell").getBoundingClientRect().width;
  floatCoins(was, view);
  fadeWebs(board, was, view);

  const slides = [];
  const deaths = [];
  const placements = [];
  // each piece that stayed on the board, from its old index to its new one
  const kept = {};
  for (const player of PLAYERS) {
    const placed = was.tiles_in_hand[player].length - view.tiles_in_hand[player].length;
    const change = diff(was.positions[player], view.positions[player], placed);
    kept[player] = change ? change.kept : [];
    if (!change) {
      continue;
    }
    for (const [from, to] of change.moved) {
      slides.push([before.pieces[player][from], view.positions[player][to]]);
    }
    for (const index of change.died) {
      deaths.push([player, before.pieces[player][index]]);
    }
    for (const index of change.appended) {
      placements.push([player, index]);
    }
  }
  if (slides.length + deaths.length + placements.length > 6) {
    return;
  }

  // a slide's length, so a piece that's also turned over waits until it's arrived
  let sliding = 0;
  for (const [from, [row, col]] of slides) {
    const piece = pieceAt(board, row, col);
    if (from && piece) {
      const duration = travel(from.rect, piece.getBoundingClientRect(), square, SLIDE_MS_PER_SQUARE);
      fly(piece, from.rect, duration);
      play("move", duration);
      sliding = Math.max(sliding, duration);
    }
  }

  // the dead are the newest tiles in the graveyard
  const graves = Array.from(document.querySelectorAll(".graveyard-contents .acc-tile"));
  const newGraves = graves.slice(was.discard.length);
  deaths.forEach(([, from], i) => {
    if (from) {
      ghostToGrave(from, newGraves[i], square);
    }
  });

  // a placed tile leaves as any tile it replaces does, and the hand closes up behind it
  if (deaths.length) {
    play("death");
  }
  const delay = deaths.length ? PAUSE_MS : 0;
  for (const [player, index] of placements) {
    const [row, col] = view.positions[player][index];
    const piece = pieceAt(board, row, col);
    const glyph = view.tiles_on_board[player][index];
    const hand = before.hands[player];
    let used = hand.findIndex((t) => t.glyph === glyph);
    if (used < 0) {
      used = hand.length - 1;
    }
    if (piece && hand[used]) {
      const from = hand[used].rect;
      const duration = travel(from, piece.getBoundingClientRect(), square, FLY_MS_PER_SQUARE, FLY_MIN_SQUARES);
      fly(piece, from, duration, delay);
      // arriving as the dead reach the graveyard, a clack would sound like theirs
      if (!deaths.length) {
        play("move", delay + duration);
      }
    }
    closeHand(player, hand.filter((_, i) => i !== used), square);
  }

  const swapped = animateExchange(board, before, view, kept, square);
  flipChanged(board, was, view, kept, swapped, sliding);
}

// How one player's pieces changed, given how the server changes its list of positions:
// a move changes a position in place, a death removes it, and a tile placed from the
// hand is appended. Returns the indexes that stayed (old to new), moved (old to new),
// died (old), and were appended (new), choosing which died so the fewest pieces moved.
function diff(was, now, placed) {
  const died = was.length - now.length + placed;
  if (placed < 0 || died < 0 || died > was.length) {
    return null;
  }
  const same = (a, b) => a[0] === b[0] && a[1] === b[1];
  let best = null;
  for (const removed of combinations(was.length, died)) {
    const kept = was
      .map((_, i) => i)
      .filter((i) => !removed.includes(i))
      .map((oldIndex, newIndex) => [oldIndex, newIndex]);
    const moved = kept.filter(([oldIndex, newIndex]) => !same(was[oldIndex], now[newIndex]));
    if (!best || moved.length < best.moved.length) {
      best = {kept, moved, died: removed, appended: now.map((_, i) => i).slice(kept.length)};
    }
  }
  return best;
}

function combinations(n, k, start = 0) {
  if (k === 0) {
    return [[]];
  }
  const result = [];
  for (let i = start; i <= n - k; i++) {
    for (const rest of combinations(n, k - 1, i + 1)) {
      result.push([i, ...rest]);
    }
  }
  return result;
}

function pieceAt(board, row, col) {
  const cell = findCell(board, row, col);
  return cell && cell.querySelector(".piece");
}

function exchangeMarks(board, row, col) {
  const cell = findCell(board, row, col);
  return cell ? cell.querySelectorAll(".cell-marks .board-tile") : [];
}

// how long it takes to go from one rect to another at `msPerSquare`, centre to centre
function travel(fromRect, toRect, square, msPerSquare, minimum = 1) {
  const dx = fromRect.left + fromRect.width / 2 - (toRect.left + toRect.width / 2);
  const dy = fromRect.top + fromRect.height / 2 - (toRect.top + toRect.height / 2);
  return msPerSquare * Math.max(minimum, Math.hypot(dx, dy) / square);
}

// draw an element at its new place as if it were still at the old rect, then let it go
function fly(element, fromRect, duration, delay = 0) {
  const to = element.getBoundingClientRect();
  const dx = fromRect.left + fromRect.width / 2 - (to.left + to.width / 2);
  const dy = fromRect.top + fromRect.height / 2 - (to.top + to.height / 2);
  const scale = fromRect.height / to.height;
  // above the squares it passes over
  element.style.zIndex = 3;
  element
    .animate(
      [{transform: `translate(${dx}px, ${dy}px) scale(${scale})`}, {transform: "none"}],
      {duration, delay, easing: "ease-out", fill: "backwards"},
    )
    .finished.then(() => element.style.removeProperty("z-index"), () => {});
}

// a copy of a tile that's left, flying from where it was to `target` (an element,
// hidden until the copy arrives; at `toRect` if given, else where it's drawn), or
// fading where it was if there's no target
function ghost(glyph, from, target, duration, pause = 0, toRect = null) {
  const element = document.createElement("span");
  element.className = "ghost";
  element.textContent = glyph;
  element.style.left = `${from.rect.left}px`;
  element.style.top = `${from.rect.top}px`;
  element.style.fontSize = from.fontSize;
  element.style.color = from.color;
  document.body.append(element);

  const total = pause + duration;
  const keyframes = [
    {transform: "none", opacity: 1},
    {transform: "none", opacity: 1, offset: pause / total},
  ];
  if (target) {
    const to = toRect || target.getBoundingClientRect();
    const dx = to.left + to.width / 2 - (from.rect.left + from.rect.width / 2);
    const dy = to.top + to.height / 2 - (from.rect.top + from.rect.height / 2);
    keyframes.push({transform: `translate(${dx}px, ${dy}px) scale(${to.height / from.rect.height})`, opacity: 0.6});
    target.animate([{opacity: 0}, {opacity: 0}], {duration: total});
  } else {
    keyframes.push({transform: "scale(0.6)", opacity: 0});
  }
  element
    .animate(keyframes, {duration: total, easing: "ease-in"})
    .finished.then(() => element.remove(), () => element.remove());
}

// a dead tile pauses where it died, then flies to its place in the graveyard
function ghostToGrave(from, grave, square) {
  const duration = grave
    ? travel(from.rect, grave.getBoundingClientRect(), square, FLY_MS_PER_SQUARE, FLY_MIN_SQUARES)
    : FLY_MS_PER_SQUARE * FLY_MIN_SQUARES;
  // the graveyard shows the tile's face, which the board may not have
  ghost(grave ? grave.textContent : from.glyph, from, grave, duration, PAUSE_MS);
}

// the tiles left in a hand slide over to where they're now drawn
function closeHand(player, left, square) {
  const tiles = document.querySelectorAll(`.strip.${player} .hand-tile`);
  if (tiles.length !== left.length) {
    return;
  }
  tiles.forEach((tile, i) => {
    const duration = travel(left[i].rect, tile.getBoundingClientRect(), square, SLIDE_MS_PER_SQUARE, 0);
    if (duration > 0) {
      fly(tile, left[i].rect, duration);
    }
  });
}

// After an exchange: if we can see it was a swap (it was ours), the new tile flies out
// of its place in the stack onto the piece's square, and the old one into that place.
// Then the server's shuffle, so neither player can tell which is which: a beat later
// the stack's two tiles change places if the shuffle changed their order, which
// whoever can see them can tell, or half the time at random for whoever can't.
// Returns the square of a piece that swapped, which isn't also turned over.
function animateExchange(board, before, view, kept, square) {
  const exchanges = (log) =>
    log.flatMap((turn) => turn.events).filter((event) => event.kind === "exchange");
  const latest = exchanges(view.public_log);
  if (latest.length <= exchanges(before.view.public_log).length) {
    return null;
  }
  const player = latest[latest.length - 1].player;
  play("exchange");
  const same = (a, b) => a[0] === b[0] && a[1] === b[1];
  for (const [oldIndex, newIndex] of kept[player] || []) {
    const position = view.positions[player][newIndex];
    const e = view.exchange_positions.findIndex((p) => same(p, position));
    if (e < 0) {
      continue;
    }
    const piece = pieceAt(board, ...position);
    const marks = Array.from(exchangeMarks(board, ...position));
    const slots = before.marks[e];
    const oldGlyph = before.view.tiles_on_board[player][oldIndex];
    const newGlyph = view.tiles_on_board[player][newIndex];
    const from = before.pieces[player][oldIndex];

    // the stack as it lay before the shuffle
    const stack = [...before.view.exchange_tiles[e]];
    let swapped = null;
    let slot = -1;
    if (oldGlyph !== newGlyph && oldGlyph !== HIDDEN_TILE && newGlyph !== HIDDEN_TILE) {
      slot = Math.max(0, stack.indexOf(newGlyph));
      stack[slot] = oldGlyph;
      swapped = position;
    }
    const shuffled = view.exchange_tiles[e];
    const visible = !shuffled.includes(HIDDEN_TILE) && !stack.includes(HIDDEN_TILE);
    const reorder =
      marks.length === 2 && slots.length === 2 &&
      (visible ? stack.some((glyph, i) => glyph !== shuffled[i]) : Math.random() < 0.5);

    let wait = 0;
    if (swapped && piece && from && slots[slot]) {
      wait = travel(slots[slot], piece.getBoundingClientRect(), square, FLY_MS_PER_SQUARE, FLY_MIN_SQUARES);
      fly(piece, slots[slot], wait);
      // the old tile lands in that place, drawn there by whichever tile will be there
      // until the shuffle
      const lands = marks[reorder ? 1 - slot : slot];
      const duration = travel(from.rect, slots[slot], square, FLY_MS_PER_SQUARE, FLY_MIN_SQUARES);
      ghost(oldGlyph, from, lands, duration, 0, slots[slot]);
      wait = Math.max(wait, duration);
    }
    if (reorder) {
      const delay = wait ? wait + SHUFFLE_BEAT_MS : 0;
      const duration = travel(slots[0], slots[1], square, SLIDE_MS_PER_SQUARE, 0.5);
      fly(marks[0], slots[1], duration, delay);
      fly(marks[1], slots[0], duration, delay);
    }
    return swapped;
  }
  return null;
}

// Turn over every tile that's been revealed, or hidden again: board pieces (also
// our own, when the opponent gets to see them), exchange tiles, and the
// hands at the end of the game.
function flipChanged(board, was, view, kept, swapped, sliding) {
  const hidden = (glyph) => glyph === HIDDEN_TILE;
  const same = (a, b) => a && b && a[0] === b[0] && a[1] === b[1];

  for (const player of PLAYERS) {
    for (const [oldIndex, newIndex] of kept[player] || []) {
      const position = view.positions[player][newIndex];
      if (same(position, swapped)) {
        continue;
      }
      const from = was.tiles_on_board[player][oldIndex];
      const to = view.tiles_on_board[player][newIndex];
      const shown =
        was.tiles_on_board_revealed[player][oldIndex] !== view.tiles_on_board_revealed[player][newIndex] ||
        hidden(from) !== hidden(to);
      const piece = pieceAt(board, ...position);
      // a piece that also moved turns over once it's arrived
      const moved = !same(was.positions[player][oldIndex], position);
      if (shown && piece) {
        flip(piece, from, to, moved ? sliding : 0);
      }
    }

    // the hands, face up at the end of the game
    const hand = document.querySelectorAll(`.strip.${player} .hand-tile`);
    if (hand.length === was.tiles_in_hand[player].length) {
      hand.forEach((tile, i) => {
        if (hidden(was.tiles_in_hand[player][i]) !== hidden(view.tiles_in_hand[player][i])) {
          flip(tile, was.tiles_in_hand[player][i], view.tiles_in_hand[player][i]);
        }
      });
    }
  }

  // an exchange's tiles, seen on stepping onto it, after the step
  view.exchange_positions.forEach(([row, col], e) => {
    const marks = exchangeMarks(board, row, col);
    marks.forEach((mark, i) => {
      const from = was.exchange_tiles[e]?.[i];
      const to = view.exchange_tiles[e][i];
      if (from && hidden(from) !== hidden(to)) {
        flip(mark, from, to, sliding);
      }
    });
  });

  // an unused tile seen with the bonus
  document.querySelectorAll(".unused-contents .acc-tile").forEach((tile, i) => {
    const from = was.unused_tiles[i];
    const to = view.unused_tiles[i];
    if (from && hidden(from) !== hidden(to)) {
      flip(tile, from, to);
    }
  });
}

// show `glyph` on a tile, keeping any mark drawn on it (an exchange's)
function setGlyph(element, glyph) {
  const text = element.firstChild;
  if (text && text.nodeType === Node.TEXT_NODE) {
    text.nodeValue = glyph;
  } else {
    element.prepend(glyph);
  }
}

// a tile turns over side to side, like a card: edge-on halfway, then the other face
function flip(element, from, to, delay = 0) {
  setGlyph(element, from);
  const turn = (start, end, easing) =>
    element.animate(
      [{transform: `perspective(400px) rotateY(${start}deg)`}, {transform: `perspective(400px) rotateY(${end}deg)`}],
      {duration: FLIP_MS / 2, easing},
    );
  play("flip", delay + FLIP_MS / 2);
  window.setTimeout(() => {
    turn(0, 90, "ease-in").finished.then(() => {
      setGlyph(element, to);
      turn(-90, 0, "ease-out");
    }, () => {});
  }, delay);
}

// A new game's tiles, dealt face down from a pile in the middle of the board, a player
// at a time: their squares, then their hands, then the exchanges, and the rest to the
// unused list.  Each tile is hidden where it's going until it arrives.  Drawn again
// meanwhile (not `start`), the tiles yet to arrive are hidden again.
function deal(board, view, start) {
  const [north, south] = PLAYERS.map((player) => [
    ...view.positions[player].map(([row, col]) => pieceAt(board, row, col)),
    ...document.querySelectorAll(`.strip.${player} .hand-tile`),
  ]);
  const targets = [];
  for (let i = 0; i < Math.max(north.length, south.length); i++) {
    targets.push(north[i], south[i]);
  }
  targets.push(...board.querySelectorAll(".exchange .cell-marks .board-tile"));
  targets.push(...document.querySelectorAll(".unused-contents .acc-tile"));

  const pile = board.getBoundingClientRect();
  const x = pile.left + pile.width / 2;
  const y = pile.top + pile.height / 2;
  const piece = board.querySelector(".piece");
  const fontSize = piece ? getComputedStyle(piece).fontSize : "40px";
  const elapsed = performance.now() - dealt;
  targets.filter(Boolean).forEach((target, i) => {
    const delay = i * DEAL_GAP_MS;
    const total = delay + DEAL_FLY_MS;
    if (!start) {
      if (total > elapsed) {
        dealing.push(target.animate([{opacity: 0}, {opacity: 0}], {duration: total - elapsed}));
      }
      return;
    }
    const tile = document.createElement("span");
    tile.className = "ghost";
    tile.textContent = HIDDEN_TILE;
    tile.style.fontSize = fontSize;
    tile.style.color = getComputedStyle(target).color;
    document.body.append(tile);
    const own = tile.getBoundingClientRect();
    tile.style.left = `${x - own.width / 2}px`;
    tile.style.top = `${y - own.height / 2}px`;
    const to = target.getBoundingClientRect();
    const dx = to.left + to.width / 2 - x;
    const dy = to.top + to.height / 2 - y;
    const flight = tile.animate(
      [
        {transform: "none"},
        {transform: "none", offset: delay / total, easing: "ease-out"},
        {transform: `translate(${dx}px, ${dy}px) scale(${to.height / own.height})`},
      ],
      {duration: total},
    );
    flight.finished.then(() => tile.remove(), () => tile.remove());
    dealing.push(flight, target.animate([{opacity: 0}, {opacity: 0}], {duration: total}));
    play("deal", total);
  });
}

// money gained or spent rises from the player's amount, and fades
function floatCoins(was, view) {
  for (const player of PLAYERS) {
    const delta = view.coins[player] - was.coins[player];
    const amount = document.querySelector(`.strip.${player} .amount`);
    if (!delta || !amount) {
      continue;
    }
    const rect = amount.getBoundingClientRect();
    const style = getComputedStyle(amount);
    const float = document.createElement("span");
    float.className = "coin-float";
    float.textContent = `${delta > 0 ? "+" : "−"}$${Math.abs(delta)}`;
    float.style.left = `${rect.right}px`;
    float.style.top = `${rect.top}px`;
    float.style.color = style.color;
    float.style.fontSize = `${parseFloat(style.fontSize) * 0.55}px`;
    document.body.append(float);
    float
      .animate(
        [
          {transform: "translate(-100%, 0)", opacity: 0},
          {transform: "translate(-100%, -40%)", opacity: 1, offset: 0.2},
          {transform: "translate(-100%, -160%)", opacity: 0},
        ],
        {duration: FLOAT_MS, easing: "ease-out"},
      )
      .finished.then(() => float.remove(), () => float.remove());
  }
}

// webs fade in where they're laid and out where they're cleared
function fadeWebs(board, was, view) {
  const has = (webs, [row, col]) => webs.some(([r, c]) => r === row && c === col);
  for (const player of PLAYERS) {
    for (const [row, col] of view.webs[player]) {
      if (!has(was.webs[player], [row, col])) {
        findCell(board, row, col)
          ?.querySelector(`.web.${player}`)
          ?.animate([{opacity: 0}, {opacity: 1}], {duration: FADE_MS, easing: "ease-out"});
      }
    }
    for (const [row, col] of was.webs[player]) {
      if (!has(view.webs[player], [row, col])) {
        const cell = findCell(board, row, col);
        if (!cell) {
          continue;
        }
        const web = document.createElement("div");
        web.classList.add("web", player);
        cell.append(web);
        web
          .animate([{opacity: 1}, {opacity: 0}], {duration: FADE_MS, easing: "ease-in", fill: "forwards"})
          .finished.then(() => web.remove(), () => web.remove());
      }
    }
  }
}

export {snapshot, animate};
