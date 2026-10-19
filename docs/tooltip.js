"use strict";

// A tile or button that says what it is and does, the moment it's hovered: one tip,
// above it (or below, without room), with a reminder that right-clicking opens more.
// It's the reference in brief: each use's price and effects, then the notes.

import {settings} from "./settings.js";

// a mouse with its right button filled
const RIGHT_CLICK =
  '<svg viewBox="0 0 12 16" aria-hidden="true">' +
  '<rect x="1" y="1" width="10" height="14" rx="5" fill="none" stroke="currentColor" stroke-width="1.2"/>' +
  '<path d="M6 1 A5 5 0 0 1 11 6 L11 7 L6 7 Z" fill="currentColor"/>' +
  '<line x1="6" y1="1" x2="6" y2="7" stroke="currentColor" stroke-width="1.2"/>' +
  "</svg>";

// how far the tip sits from what it describes, and from the window's edges
const GAP = 8;
const MARGIN = 8;

// `describe(target)` gives {element, name, uses, notes} for whatever is under the
// pointer (see renderState.ruleOf), or null
function setUpTooltips(describe) {
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  document.body.append(tip);
  let showing = null;

  const hide = () => {
    tip.hidden = true;
    showing = null;
  };

  document.addEventListener("mouseover", ({ target }) => {
    const found = settings.tooltips ? describe(target) : null;
    if (!found) {
      hide();
      return;
    }
    if (found.element === showing) {
      return;
    }
    showing = found.element;
    tip.replaceChildren();
    const name = document.createElement("div");
    name.className = "tip-name";
    name.textContent = found.name;
    tip.append(name);
    found.uses.forEach((use, i) => {
      use.lines.forEach((line, j) => {
        const text = document.createElement("div");
        // a second use is an alternative; a use's price leads its first line
        if (j === 0 && i > 0) {
          text.append(span("tip-or", "or "));
        }
        if (j === 0 && use.price) {
          text.append(span(`tip-price ${use.price.kind}`, use.price.text), " ");
        }
        text.append(line);
        tip.append(text);
      });
    });
    for (const [mark, line] of found.notes) {
      const note = document.createElement("div");
      note.className = "tip-note";
      note.append(span("tip-mark", mark), line);
      tip.append(note);
    }
    const more = document.createElement("div");
    more.className = "tip-more";
    more.innerHTML = `${RIGHT_CLICK}<span>right-click for more</span>`;
    tip.append(more);
    tip.hidden = false;
    place(tip, found.element.getBoundingClientRect());
  });
  // anything that changes the page under the pointer takes the tip away
  for (const event of ["mousedown", "contextmenu", "scroll", "keydown", "blur"]) {
    window.addEventListener(event, hide, true);
  }
  document.addEventListener("mouseleave", hide);
}

function span(className, text) {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = text;
  return element;
}

function place(tip, rect) {
  const width = tip.offsetWidth;
  const height = tip.offsetHeight;
  let top = rect.top - GAP - height;
  if (top < MARGIN) {
    top = rect.bottom + GAP;
  }
  const centre = rect.left + rect.width / 2;
  const left = Math.min(Math.max(centre - width / 2, MARGIN), window.innerWidth - width - MARGIN);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

export {setUpTooltips};
