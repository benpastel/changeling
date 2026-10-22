"use strict";

// A note that points at part of the page: the tutorial's steps, and the tips that come
// up the first time something happens (see tutorial.js).
//
// A note is a card with a pointer on one edge, aimed at what it's about, and a ring
// around each thing it's showing.  Dimmed, everything but the rings is shaded and
// nothing else can be clicked; undimmed, the game carries on around it.
//
// What a note points at is found afresh every frame, since the game redraws the board
// whenever it likes and the window can change size; when what it points at is gone,
// the note says so (`gone`).

// how far a ring sits outside what it rings, the card from a ring, and the card from
// the window's edges
const PAD = 6;
const GAP = 14;
const MARGIN = 10;
// how near the card's corners its pointer can be
const INSET = 18;

const SVG = "http://www.w3.org/2000/svg";

// the box around some rects, or null for none
function union(rects) {
  if (rects.length === 0) {
    return null;
  }
  const left = Math.min(...rects.map((r) => r.left));
  const top = Math.min(...rects.map((r) => r.top));
  const right = Math.max(...rects.map((r) => r.right));
  const bottom = Math.max(...rects.map((r) => r.bottom));
  return {left, top, right, bottom, width: right - left, height: bottom - top};
}

function grow(rect, by) {
  return union([{
    left: rect.left - by, top: rect.top - by, right: rect.right + by, bottom: rect.bottom + by,
  }]);
}

function overlap(a, b) {
  const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return width > 0 && height > 0 ? width * height : 0;
}

// the rects of whatever's showing of `elements`
function rectsOf(elements) {
  return elements
    .filter((element) => element?.isConnected)
    .map((element) => element.getBoundingClientRect())
    .filter((rect) => rect.width > 0 && rect.height > 0);
}

// Where a card of `size` goes, pointing at one of `targets`, keeping off the rest of
// them and everything in `avoid`, and inside `room`: on the first of `sides` where it
// fits, as near the middle of its target's side as it can be.  Says the side, the
// card's corner, how far along its edge the pointer is, and which target it points at.
// Failing everywhere, it takes whichever spot covers least.
function placeCard(size, targets, avoid, room, sides = ["below", "above", "right", "left"]) {
  const {width, height} = size;
  const across = (side) => side === "above" || side === "below";
  const candidates = [];
  for (const [rank, side] of sides.entries()) {
    for (const [aim, target] of targets.entries()) {
      // the card's edge facing the target, and the range it can slide along, keeping
      // the pointer on the target and the card in the room
      let main;
      if (side === "below") main = target.bottom + GAP;
      if (side === "above") main = target.top - GAP - height;
      if (side === "right") main = target.right + GAP;
      if (side === "left") main = target.left - GAP - width;
      const length = across(side) ? width : height;
      const [start, end] = across(side) ? [target.left, target.right] : [target.top, target.bottom];
      const [roomStart, roomEnd] = across(side) ? [room.left, room.right] : [room.top, room.bottom];
      // the pointer can be anywhere from INSET to length - INSET along the edge, and
      // must land a little inside the target
      const inside = Math.min(8, (end - start) / 2);
      const lowest = Math.max(roomStart, start + inside - (length - INSET));
      const highest = Math.min(roomEnd - length, end - inside - INSET);
      const clamp = (value) => Math.min(Math.max(value, lowest), Math.max(lowest, highest));
      const keepOff = [...targets, ...avoid];

      // centred on the target, then pushed clear of each thing it would cover
      const slides = [(start + end) / 2 - length / 2];
      for (const rect of keepOff) {
        const [rectStart, rectEnd] = across(side) ? [rect.left, rect.right] : [rect.top, rect.bottom];
        slides.push(rectStart - length, rectEnd);
      }
      for (const slide of slides) {
        const along = clamp(slide);
        const [left, top] = across(side) ? [along, main] : [main, along];
        const box = {left, top, right: left + width, bottom: top + height};
        const off = Math.max(0, room.left - box.left, room.top - box.top, box.right - room.right, box.bottom - room.bottom);
        const covered = keepOff.reduce((sum, rect) => sum + overlap(box, rect), 0);
        // the pointer, as near the target's middle as the card's edge allows
        const middle = (start + end) / 2 - along;
        const point = Math.min(Math.max(middle, INSET), length - INSET);
        candidates.push({
          side, left, top, point, aim,
          bad: off * 1e6 + covered, rank, shift: Math.abs(slide - slides[0]),
        });
      }
    }
  }
  candidates.sort((a, b) => a.bad - b.bad || a.rank - b.rank || a.aim - b.aim || a.shift - b.shift);
  return candidates[0];
}

// a rect with rounded corners, as a path
function roundRect({left, top, width, height}, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  return `M${left + r},${top}h${width - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${height - 2 * r}` +
    `a${r},${r} 0 0 1 ${-r},${r}h${-(width - 2 * r)}a${r},${r} 0 0 1 ${-r},${-r}` +
    `v${-(height - 2 * r)}a${r},${r} 0 0 1 ${r},${-r}z`;
}

class Guide {
  constructor() {
    this.root = document.createElement("div");
    this.root.className = "guide";
    this.root.hidden = true;
    this.shade = document.createElementNS(SVG, "svg");
    this.shade.classList.add("guide-shade");
    this.shadePath = document.createElementNS(SVG, "path");
    this.shadePath.setAttribute("fill-rule", "evenodd");
    this.shade.append(this.shadePath);
    this.rings = document.createElement("div");
    this.card = document.createElement("div");
    this.card.className = "guide-card";
    this.card.setAttribute("role", "dialog");
    this.root.append(this.shade, this.rings, this.card);
    document.body.append(this.root);

    this.note = null;
    this.frame = 0;
    this.laidOut = "";
    window.addEventListener("keydown", (event) => this.key(event), true);
  }

  get showing() {
    return this.note !== null;
  }

  // Show a note, replacing any other:
  //   text      what it says
  //   point     () => the elements the pointer can aim at, whichever suits
  //   spots     () => the elements to ring, each on its own; by default `point`'s
  //   avoid     () => other elements the card mustn't cover
  //   dim       shade everything else, and take the clicks and keys
  //   sides     the sides of its target the card would rather be on, in order
  //   primary   [label, onClick], the button that moves on
  //   secondary [label, onClick], the quiet one that stops
  //   gone      called once if what it points at disappears, or `holds()` stops holding
//   holds     () => whether it's still wanted
  show(note) {
    this.note = {...note, spots: note.spots ?? note.point, avoid: note.avoid ?? (() => [])};
    this.root.hidden = false;
    this.root.classList.toggle("dim", Boolean(note.dim));
    this.card.replaceChildren();
    const text = document.createElement("div");
    text.className = "guide-text";
    text.innerHTML = note.text;
    const buttons = document.createElement("div");
    buttons.className = "guide-buttons";
    const button = ([label, onClick], className) => {
      const element = document.createElement("button");
      element.className = className;
      element.textContent = label;
      element.addEventListener("click", onClick);
      return element;
    };
    if (note.secondary) {
      buttons.append(button(note.secondary, "guide-secondary"));
    }
    if (note.primary) {
      buttons.append(button(note.primary, "guide-primary"));
    }
    this.card.append(text, buttons);
    this.laidOut = "";
    if (!this.frame) {
      this.tick();
    }
  }

  hide() {
    this.note = null;
    this.root.hidden = true;
    window.cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  key(event) {
    if (!this.note?.dim) {
      return;
    }
    // the tutorial has the keyboard to itself
    if (event.key === "Escape" && this.note.secondary) {
      this.note.secondary[1]();
    } else if ((event.key === "Enter" || event.key === "ArrowRight") && this.note.primary) {
      this.note.primary[1]();
    } else {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
  }

  tick() {
    this.frame = window.requestAnimationFrame(() => this.tick());
    const note = this.note;
    const pointed = rectsOf(note.point());
    if (note.gone && (pointed.length === 0 || (note.holds && !note.holds()))) {
      const gone = note.gone;
      this.hide();
      gone();
      return;
    }
    // a ring at the window's edge stays inside it
    const inWindow = (rect) => union([{
      left: Math.max(rect.left, 1), top: Math.max(rect.top, 1),
      right: Math.min(rect.right, window.innerWidth - 1), bottom: Math.min(rect.bottom, window.innerHeight - 1),
    }]);
    const spots = rectsOf(note.spots()).map((rect) => inWindow(grow(rect, PAD)));
    const avoid = rectsOf(note.avoid());
    const room = {left: MARGIN, top: MARGIN, right: window.innerWidth - MARGIN, bottom: window.innerHeight - MARGIN};
    // only when something has moved
    const key = JSON.stringify([pointed, spots, avoid, room, this.card.offsetWidth, this.card.offsetHeight]);
    if (key !== this.laidOut) {
      this.laidOut = key;
      this.layOut(pointed, spots, avoid, room);
    }
  }

  layOut(pointed, spots, avoid, room) {
    const targets = pointed.map((rect) => grow(rect, PAD));
    this.shadePath.setAttribute("d",
      `M0,0H${window.innerWidth}V${window.innerHeight}H0z` + spots.map((rect) => roundRect(rect, 8)).join(""));
    this.rings.replaceChildren(...spots.map((rect) => {
      const ring = document.createElement("div");
      ring.className = "guide-ring";
      Object.assign(ring.style, {
        left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`,
      });
      return ring;
    }));

    const card = this.card;
    card.className = "guide-card";
    const size = {width: card.offsetWidth, height: card.offsetHeight};
    if (targets.length === 0) {
      // nothing to point at: the middle of the window
      card.style.left = `${(window.innerWidth - size.width) / 2}px`;
      card.style.top = `${(window.innerHeight - size.height) / 2}px`;
      return;
    }
    const placed = placeCard(size, targets, [...spots, ...avoid.map((rect) => grow(rect, PAD))], room, this.note.sides);
    // what it points at, for the tests to hold the pointer to
    this.root.dataset.target = JSON.stringify(targets[placed.aim]);
    this.root.dataset.targets = JSON.stringify(targets);
    card.classList.add(placed.side);
    card.style.left = `${placed.left}px`;
    card.style.top = `${placed.top}px`;
    card.style.setProperty("--point", `${placed.point}px`);
  }
}

export {Guide};
