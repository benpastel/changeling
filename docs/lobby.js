"use strict";

// The lobby (your name and the open tables) and the table room (who's playing, and with
// which tiles, before the match starts).
//
// You're always blue and whoever you'll play is red, as in the game, so the room is laid
// out like the board: them above, the tiles between, you below.

import {
  HIDDEN_TILE,
  ALL_TILES,
  ACTION_NAMES,
  TILES_PER_GAME,
} from "./constants.js";

const TILE_MODES = ["starter", "random", "custom"];
// must match python clock.TIME_MODES
const TIME_MODES = ["fast", "medium", "slow", "unlimited"];
// must match python bots.LEVELS
const BOT_LEVELS = ["easy", "medium", "hard"];
const EVERY_TILE = ALL_TILES.map(([tile]) => tile);

function element(tag, className, text) {
  const e = document.createElement(tag);
  if (className) {
    e.className = className;
  }
  if (text !== undefined) {
    e.textContent = text;
  }
  return e;
}

function button(className, text, onClick, disabled = false) {
  const b = element("button", className, text);
  b.disabled = disabled;
  b.addEventListener("click", onClick);
  return b;
}

// the tiles a table will play: face down when they're drawn fresh every game, and an
// empty slot for each still to be picked
function setPreview(mode, tiles, className) {
  const preview = element("div", `tile-set ${className}`);
  if (mode === "random") {
    preview.textContent = HIDDEN_TILE.repeat(TILES_PER_GAME);
    return preview;
  }
  preview.textContent = tiles.join("");
  for (let i = tiles.length; i < TILES_PER_GAME; i++) {
    preview.append(element("span", "slot"));
  }
  return preview;
}

function setUpLobby(panel, actions) {
  panel.querySelector(".new-table").addEventListener("click", actions.newTable);
  panel.querySelector(".play-bot").addEventListener("click", actions.playBot);
}

function renderLobby(panel, tables, named, actions) {
  // nothing works until you've given a name
  panel.classList.toggle("locked", !named);
  for (const b of panel.querySelectorAll(".lobby-actions button")) {
    b.disabled = !named;
  }

  const list = panel.querySelector(".table-list");
  list.innerHTML = "";
  list.hidden = tables.length === 0;
  if (tables.length) {
    list.append(element("div", "list-head", "open tables"));
  }
  for (const table of tables) {
    const row = element("div", "table-row");
    const host = Object.values(table.seats).find((name) => name !== null) ?? "";
    row.append(
      element("span", "row-name them", host),
      setPreview(table.mode, table.tiles, "row-tiles"),
      button("btn small", "join", () => actions.join(table.id), !named),
    );
    list.append(row);
  }
}

function renderOpponent(table, actions) {
  const seat = element("div", "seat them");
  const side = table.mySide === "north" ? "south" : "north";
  const occupant = table.seats[side];
  const buttons = element("div", "seat-buttons");

  if (occupant === null) {
    seat.append(element("span", "seat-name empty", "waiting for an opponent"));
    const copy = button("btn small", "copy invite", () => {
      const link = `${location.origin}${location.pathname}#/t/${table.id}`;
      navigator.clipboard?.writeText(link).then(() => {
        copy.textContent = "copied";
        window.setTimeout(() => { copy.textContent = "copy invite"; }, 1400);
      }, () => undefined);
    });
    buttons.append(copy);
    if (table.amHost) {
      buttons.append(button("btn small", "add bot", actions.addBot));
    }
  } else {
    const name = element("span", "seat-name", occupant.name);
    name.classList.toggle("gone", !occupant.connected);
    seat.append(name);
    if (occupant.bot) {
      // how well it plays; only the host can change it
      const levels = element("div", "segmented small");
      for (const level of BOT_LEVELS) {
        levels.append(button(level === table.botLevel ? "on" : "", level, () => actions.setBotLevel(level), !table.amHost));
      }
      buttons.append(levels);
    }
    if (occupant.bot && table.amHost) {
      buttons.append(button("btn small", "remove", actions.removeBot));
    }
  }
  seat.append(buttons);
  return seat;
}

// the tiles the table will play, named; clicking one shows what it does, or, while
// the host is picking, takes it out again
function renderSet(table, actions) {
  const set = element("div", "room-set");
  const picking = table.mode === "custom" && table.amHost;
  for (let i = 0; i < TILES_PER_GAME; i++) {
    const tile = table.mode === "random" ? HIDDEN_TILE : table.tiles[i];
    if (!tile) {
      set.append(element("span", "set-tile empty"));
      continue;
    }
    const entry = button("set-tile", "", () => {
      if (picking) {
        actions.setTiles("custom", table.tiles.filter((t) => t !== tile));
      } else {
        // a random table could draw any of them
        actions.showRules(tile === HIDDEN_TILE ? EVERY_TILE : [tile]);
      }
    });
    entry.append(element("span", "set-glyph", tile));
    if (tile !== HIDDEN_TILE) {
      entry.append(element("span", "set-name", ACTION_NAMES[tile]));
      // described on hover (see tooltip.js)
      entry.dataset.tile = tile;
    }
    set.append(entry);
  }
  return set;
}

// every tile, pale until picked, in the order picked
function renderPicker(table, actions) {
  const picker = element("div", "picker");
  const full = table.tiles.length >= TILES_PER_GAME;
  for (const [tile, name] of ALL_TILES) {
    const chosen = table.tiles.includes(tile);
    const pick = element("div", "pick");
    pick.classList.toggle("on", chosen);
    const glyph = button("pick-tile", tile, () => {
      const tiles = chosen ? table.tiles.filter((t) => t !== tile) : [...table.tiles, tile];
      actions.setTiles("custom", tiles);
    }, full && !chosen);
    pick.dataset.tile = tile;
    pick.append(glyph, element("span", "pick-name", name));
    picker.append(pick);
  }
  return picker;
}

// starter, random, or custom; only the host can change it
function renderTiles(table, actions) {
  const area = element("div", "tiles-area");

  const modes = element("div", "segmented");
  for (const mode of TILE_MODES) {
    const b = button(mode === table.mode ? "on" : "", mode, () => {
      // custom starts from nothing picked
      actions.setTiles(mode, mode === "custom" ? [] : table.tiles);
    }, !table.amHost);
    modes.append(b);
  }
  area.append(modes, renderSet(table, actions));

  if (table.mode === "custom" && table.amHost) {
    area.append(
      renderPicker(table, actions),
      button("link about-tiles", "what each tile does", () => actions.showRules(EVERY_TILE)),
    );
  }
  return area;
}

// the move clocks; only the host can change them
function renderTime(table, actions) {
  const area = element("div", "time-area");
  const modes = element("div", "segmented");
  for (const mode of TIME_MODES) {
    modes.append(button(mode === table.time ? "on" : "", mode, () => actions.setTime(mode), !table.amHost));
  }
  area.append(modes);
  return area;
}

function renderRoom(panel, table, actions) {
  panel.innerHTML = "";

  const card = element("div", "room-card");
  const you = element("div", "seat you");
  you.append(element("span", "seat-name", table.seats[table.mySide]?.name ?? ""));
  card.append(renderOpponent(table, actions), renderTiles(table, actions), renderTime(table, actions), you);

  const full = Object.values(table.seats).every((occupant) => occupant !== null);
  const ready = table.mode === "random" || table.tiles.length === TILES_PER_GAME;
  const foot = element("div", "room-foot");
  if (table.amHost) {
    foot.append(button("btn primary", "start", actions.start, !(full && ready)));
  }
  foot.append(button("btn", "leave", actions.leave));

  panel.append(card, foot);
}

export {setUpLobby, renderLobby, renderRoom};
