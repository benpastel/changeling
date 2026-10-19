// this websocket client runs in the player's browser
// it shows the lobby and table room, then the board: it listens for moves, and sends
// moves to the server

import {
  createBoard,
  renderBoard,
  renderLog,
  renderHand,
  renderOther,
  renderRules,
  ruleLines,
  renderWebs,
} from "./renderState.js";

import {ACTION_NAMES, DESCRIPTIONS} from "./constants.js";

import {renderSelection} from "./renderSelection.js";
import {renderChoice} from "./renderChoice.js";

import {snapshot, animate} from "./animate.js";
import {confetti} from "./confetti.js";
import {renderTray} from "./tray.js";

import {highlightSquares} from "./renderHighlights.js";

import {setUpLobby, renderLobby, renderRoom} from "./lobby.js";

import {Net} from "./net.js";


// This counter identifies the most recent input request we've received from the server
// we include it in all outgoing changes so that the server can ignore anything stale.
//
// 0 means we aren't waiting for any input.
let CHOICE_ID = 0;

// remembered across visits, so a refresh puts you back in your seat
const ID_KEY = "arena.playerId";
const NAME_KEY = "arena.name";
// which layout of the left column this browser last chose: "tray", or the lists
const LAYOUT_KEY = "arena.layout";

function load(key) {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function save(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private windows may refuse; we just won't remember
  }
}

// the table in the url, which we join once we have a name
function hashTable() {
  const match = window.location.hash.match(/^#\/t\/([a-z0-9]+)/i);
  return match ? match[1] : null;
}

function setHash(hash) {
  if (window.location.hash !== hash) {
    window.history.replaceState(null, "", hash);
  }
}

// which screen is showing: "lobby", "room", or "game"
function showScreen(screen) {
  document.body.className = `at-${screen}`;
  if (screen !== "game") {
    document.querySelector(".result").hidden = true;
  }
}

// the opponent's side, given ours
function otherSide(side) {
  return side === "north" ? "south" : "north";
}

window.addEventListener("DOMContentLoaded", () => {
  const container = document.querySelector(".container");
  const board = document.querySelector(".board");
  const topStrip = container.querySelector(".strip.top");
  const bottomStrip = container.querySelector(".strip.bottom");
  const log = document.querySelector(".log");
  const rules = document.querySelector(".rules");
  const tray = document.querySelector(".tray");

  // the board and strips are drawn from our side: ours at the bottom, theirs at the top
  let orientation = null;
  let lastView = null;
  function orient(mySide) {
    const side = mySide || "south";
    if (side === orientation) {
      return;
    }
    orientation = side;
    container.classList.toggle("me-north", side === "north");
    for (const [strip, owner] of [[topStrip, otherSide(side)], [bottomStrip, side]]) {
      strip.classList.remove("north", "south");
      strip.classList.add(owner);
    }
    createBoard(board, side);
    if (lastView) {
      renderGame(lastView);
    }
  }
  orient("south");

  const lobby = document.querySelector(".lobby");
  const room = document.querySelector(".room");
  const nameInput = lobby.querySelector(".name-input");
  const netbar = document.querySelector(".netbar");
  const toast = document.querySelector(".toast");

  // the latest picks / claim, redrawn whenever the board is
  // and the latest highlights, whose actions and targets are drawn on the board too,
  // and whose other choices are offered beside the board's squares
  let selection = null;
  let highlight = null;
  const redrawSelection = () => {
    renderSelection(board, selection, highlight);
    drawTurn();
  };

  function renderGame(player_view) {
    const before = snapshot(board);
    renderBoard(board, player_view);
    renderLog(log, player_view);
    renderWebs(board, player_view);
    renderHand(player_view);
    renderOther(player_view);
    renderTray(tray, player_view, orientation);
    redrawSelection();
    animate(before, board, player_view);
  }

  // the turn is shown in the strip of whoever the game is waiting on: what to do in
  // ours, or what they're doing in theirs; a choice with a panel of its own is asked
  // there instead, and once it's made the strip stays quiet until the next prompt
  let turn = {prompt: "", choiceId: 0, waiting: false, asked: false};
  function showTurn(prompt, choiceId, waiting) {
    turn = {prompt, choiceId, waiting, asked: false};
    redrawSelection();
  }
  function drawTurn() {
    const ours = turn.choiceId > 0;
    const panel = renderChoice(board, selection, highlight, orientation, ours ? turn.prompt : "");
    turn.asked ||= panel && ours;
    let acting = null;
    if (ours) {
      acting = bottomStrip;
    } else if (turn.waiting) {
      acting = topStrip;
    }
    for (const strip of [topStrip, bottomStrip]) {
      strip.classList.toggle("acting", strip === acting);
      const shown = strip === acting && !(ours && turn.asked);
      strip.querySelector(".turn-note").textContent = shown ? turn.prompt : "";
    }
  }
  window.addEventListener("resize", redrawSelection);

  // each player's reserve, and for whoever is deciding, the seconds left of this
  // decision's allowance; once those are gone their reserve counts down instead
  let clock = null;
  function showClocks() {
    for (const strip of [topStrip, bottomStrip]) {
      const owner = strip.classList.contains("north") ? "north" : "south";
      const allowance = strip.querySelector(".allowance");
      const reserve = strip.querySelector(".reserve");
      if (!clock) {
        allowance.textContent = reserve.textContent = "";
        continue;
      }
      let left = clock.reserve[owner];
      const running = clock.running === owner;
      let onReserve = false;
      if (running) {
        const now = Date.now();
        allowance.textContent = Math.ceil(Math.max(0, clock.allowanceEnds - now) / 1000);
        onReserve = now >= clock.allowanceEnds;
        left = Math.max(0, left - Math.max(0, now - clock.allowanceEnds));
      } else {
        allowance.textContent = "";
      }
      strip.querySelector(".clock").classList.toggle("stopped", !running);
      allowance.classList.toggle("idle", onReserve);
      reserve.classList.toggle("idle", running && !onReserve);
      const seconds = Math.ceil(left / 1000);
      reserve.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    }
  }
  window.setInterval(() => {
    if (clock?.running) {
      showClocks();
    }
  }, 200);

  let welcomed = false;
  let table = null;
  let tables = [];
  let wantTable = hashTable();

  const named = () => nameInput.value.trim().length > 0;

  const net = new Net(
    () => ({type: "hello", playerId: load(ID_KEY) || null, name: load(NAME_KEY)}),
    onMessage,
    onStatus,
  );

  const actions = {
    join: (tableId) => net.send({type: "joinTable", tableId}),
    leave: () => net.send({type: "leaveTable"}),
    addBot: () => net.send({type: "addBot"}),
    removeBot: () => net.send({type: "removeBot"}),
    setTiles: (mode, tiles) => net.send({type: "setTiles", mode, tiles}),
    setTime: (mode) => net.send({type: "setTime", mode}),
    setBotLevel: (level) => net.send({type: "setBotLevel", level}),
    start: () => net.send({type: "start"}),
    // before a game, the reference shows whichever tiles were clicked
    showRules: (entries) => {
      // must match python DEFAULT_SMITE_COST; random tables vary it, but show no smite
      renderRules(rules.querySelector(".rules-list"), {smite_cost: 10}, entries);
      openRules();
    },
  };

  function maybeJoin() {
    if (welcomed && wantTable && named() && (!table || table.id !== wantTable)) {
      actions.join(wantTable);
    }
  }

  nameInput.value = load(NAME_KEY);
  nameInput.addEventListener("input", () => {
    const name = nameInput.value.trim();
    save(NAME_KEY, name);
    net.send({type: "setName", name});
    renderLobby(lobby, tables, named(), actions);
  });
  // a pasted table link joins once the name is entered, not on its first letter
  nameInput.addEventListener("change", maybeJoin);
  setUpLobby(lobby, {
    newTable: () => net.send({type: "createTable"}),
    playBot: () => net.send({type: "createTable", bot: true}),
  });
  // the reference for the tiles in play: one click opens it over most of the screen
  const openRules = () => { rules.hidden = false; };
  const closeRules = () => { rules.hidden = true; };
  // in the lists layout, the tiles in play open what every tile does; in the tray, a
  // row, or the smite cost, opens what it does
  const showRules = (entries) => {
    if (lastView) {
      renderRules(rules.querySelector(".rules-list"), lastView, entries);
      openRules();
    }
  };
  document.querySelector(".in-play").addEventListener("click", () => showRules(undefined));
  tray.addEventListener("click", ({ target }) => {
    const row = target.closest(".tray-row");
    if (row) {
      showRules([row.dataset.tile]);
    }
  });
  document.querySelector(".tray-side .smite-cost").addEventListener("click", () => showRules(["⚡"]));

  // any tile or button in the game says what it is and does when hovered, and opens
  // its own reference when right-clicked
  const describedAt = (target) => {
    for (let element = target; element && element !== container; element = element.parentElement) {
      const {name, tileName, tile} = element.dataset;
      const glyph = name ?? tileName ?? tile ?? (element.children.length === 0 ? element.textContent.trim() : "");
      if (glyph in DESCRIPTIONS) {
        return {element, glyph};
      }
    }
    return null;
  };
  container.addEventListener("mouseover", ({ target }) => {
    const found = lastView && describedAt(target);
    if (found) {
      found.element.title = [ACTION_NAMES[found.glyph], ...ruleLines(found.glyph, lastView)].join("\n");
    }
  });
  container.addEventListener("contextmenu", (event) => {
    const found = lastView && describedAt(event.target);
    if (found) {
      event.preventDefault();
      showRules([found.glyph]);
    }
  });

  // the left column's layout, switched from the corner and remembered
  const layoutToggle = document.querySelector(".layout-toggle");
  function setLayout(tray) {
    container.classList.toggle("tray-layout", tray);
    layoutToggle.textContent = tray ? "lists" : "tray";
    layoutToggle.title = tray ? "show the graveyard, unused, and unknown lists" : "show every tile in a tray";
    save(LAYOUT_KEY, tray ? "tray" : "lists");
  }
  setLayout(load(LAYOUT_KEY) === "tray");
  layoutToggle.addEventListener("click", () => setLayout(!container.classList.contains("tray-layout")));
  rules.querySelector(".rules-close").addEventListener("click", closeRules);
  rules.addEventListener("click", ({ target }) => {
    if (target === rules) {
      closeRules();
    }
  });
  window.addEventListener("keydown", ({ key }) => {
    if (key === "Escape") {
      closeRules();
    }
  });

  // how the game went, and the match so far, until we choose what's next
  const result = document.querySelector(".result");
  let resultChoice = 0;
  function showResult(outcome, choiceId) {
    const shown = !result.hidden;
    result.hidden = !outcome;
    resultChoice = choiceId;
    if (!outcome) {
      return;
    }
    const me = table?.mySide || "south";
    const them = otherSide(me);
    const who = (side) => (side === me ? "you" : "them");

    const title = result.querySelector(".result-title");
    title.className = `result-title ${outcome.winner ? who(outcome.winner) : ""}`;
    title.textContent = outcome.winner ? `${outcome.names[outcome.winner]} wins!` : "A draw!";

    const cell = (tag, text, className = "") => {
      const element = document.createElement(tag);
      element.textContent = text;
      element.className = className;
      return element;
    };
    const head = document.createElement("thead");
    const names = document.createElement("tr");
    names.append(cell("th", ""), cell("th", outcome.names[me], "you"), cell("th", outcome.names[them], "them"));
    head.append(names);
    const body = document.createElement("tbody");
    for (const [label, counts] of [
      ["this game", outcome.game],
      ["games won", outcome.wins],
      ["total points", outcome.points],
    ]) {
      const row = document.createElement("tr");
      row.append(cell("th", label), cell("td", counts[me], "you"), cell("td", counts[them], "them"));
      body.append(row);
    }
    result.querySelector(".result-table").replaceChildren(head, body);

    if (!shown && outcome.winner) {
      const color = outcome.winner === me ? "#1f4fb4" : "#c4302b";
      confetti([color, color, "#141414", "#9a9a9a"]);
    }
  }
  const answerResult = (data) => {
    net.send({choiceId: resultChoice, data});
    result.hidden = true;
  };
  result.querySelector(".next-game").addEventListener("click", () => answerResult({}));
  result.querySelector(".back-to-table").addEventListener("click", () => answerResult({back: true}));

  for (const quit of document.querySelectorAll(".quit")) {
    quit.addEventListener("click", () => {
      if (window.confirm("End this match for both players?")) {
        net.send({type: "quit"});
      }
    });
  }

  window.addEventListener("hashchange", () => {
    wantTable = hashTable();
    maybeJoin();
  });

  function onStatus(status) {
    netbar.hidden = status === "open" || !welcomed;
    netbar.textContent = status === "replaced" ? "open in another tab" : "reconnecting…";
  }

  function onMessage(event) {
    switch (event.type) {
      case "welcome":
        welcomed = true;
        save(ID_KEY, event.playerId);
        if (document.activeElement !== nameInput) {
          nameInput.value = event.name;
        }
        maybeJoin();
        break;
      case "lobby":
        tables = event.tables;
        if (!table) {
          if (!wantTable) {
            setHash("#/");
          }
          renderLobby(lobby, tables, named(), actions);
          showScreen("lobby");
          if (!named()) {
            nameInput.focus();
          }
        }
        break;
      case "table":
        table = event.table;
        wantTable = table.id;
        setHash(`#/t/${table.id}`);
        if (table.playing) {
          orient(table.mySide);
          container.classList.toggle("timed", table.time !== "unlimited");
          showScreen("game");
        } else {
          renderRoom(room, table, actions);
          showScreen("room");
        }
        break;
      case "left":
        table = null;
        wantTable = null;
        setHash("#/");
        break;
      case "error":
        toast.textContent = event.message;
        toast.hidden = false;
        window.setTimeout(() => { toast.hidden = true; }, 2600);
        break;
      default:
        handleGameEvent(event);
    }
  }

  function handleGameEvent(event) {
    if (event.type === "STATE_CHANGE") {
      // update the UI with changes to the persistent game state
      lastView = event["playerView"];
      renderGame(lastView);
    } else if (event.type === "SELECTION_CHANGE") {
      // update the UI with changes to the current (partially) selected moves.
      // the server should call this again with null selections to clear the highlights.
      const {player, start, action, target, reflect} = event;
      selection = player || start || action || target ? {player, start, action, target, reflect} : null;
      redrawSelection();
    } else if (event.type === "HIGHLIGHT_CHANGE") {
      // highlight possible squares or tiles; actions and responses are drawn on the
      // board, and the action panel below it is only for reference
      // the server should call this again with empty lists to clear the highlights
      highlight = event;
      highlightSquares(event["squares"], board, table?.mySide);
      redrawSelection();
    } else if (event.type === "PROMPT") {
      CHOICE_ID = parseInt(event.choiceId);
      showTurn(event.prompt, CHOICE_ID, event.waiting);
    } else if (event.type === "CLOCK") {
      // the server's times, moved onto ours
      const offset = Date.now() - event.sent;
      clock = {...event, allowanceEnds: event.allowanceEnds + offset};
      showClocks();
    } else if (event.type === "MATCH_CHANGE") {
      // how the game went, until we move on; null once we have
      showResult(event.result, event.choiceId);
    }
  }

  sendSelection(board, net);

  net.connect();
});

function sendSelection(board, net) {
  // send all clicks on the board
  board.addEventListener("click", ({ target }) => {
    // a tile or answer in a choice's panel
    const pick = target.closest(".choice-panel .option");
    if (pick) {
      net.send({choiceId: CHOICE_ID, data: {[pick.dataset.pick]: pick.dataset.name}});
      return;
    }
    // an ability or response drawn on the board; one in a square also picks that square
    const option = target.closest(".option");
    if (option) {
      const data = {button: option.dataset.name};
      const optionCell = option.closest(".cell");
      if (optionCell) {
        data.row = parseInt(optionCell.dataset.row);
        data.column = parseInt(optionCell.dataset.column);
      }
      net.send({choiceId: CHOICE_ID, data});
      return;
    }
    if (target.closest(".claim-note")) {
      return;
    }

    // send the square's (row, column)
    // and let the server decide if it's a valid start or target
    const cell = target.closest(".cell");
    if (!cell) {
      return;
    }
    const row = parseInt(cell.dataset.row);
    const column = parseInt(cell.dataset.column);

    const data = {};

    if (Number.isInteger(row) && Number.isInteger(column)) {
      data.row = row;
      data.column = column;
    }

    net.send({
      choiceId: CHOICE_ID,
      data
    });
  });
}
