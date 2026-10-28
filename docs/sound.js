"use strict";

// The game's sounds: the clack of mahjong tiles as they move and fall, and a few soft
// notes for what needs your attention.  Minimal on purpose, like a chess site's.
//
// They're synthesized, not recorded: a few lines of Web Audio each, so there's
// nothing to download and each can be tuned here.  Any can become a recording later
// without anything that calls play() changing.
//
// On by default, at the volume in the settings; browsers keep a page quiet until it's
// first clicked, so the first click anywhere wakes it.

const ON_KEY = "arena.sound";
const VOLUME_KEY = "arena.volume";

function load(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // private windows may refuse; it holds until the page is closed
  }
}

const stored = Number(load(VOLUME_KEY) ?? NaN);
const sound = {
  on: load(ON_KEY) !== "off",
  volume: stored >= 0 && stored <= 1 ? stored : 0.7,
};

let ctx = null;
let master = null;
let noise = null;

function wake() {
  if (typeof AudioContext === "undefined") {
    return;
  }
  if (!ctx) {
    ctx = new AudioContext();
    master = ctx.createGain();
    master.gain.value = sound.volume;
    // a gentle limiter, so a pile of clacks at once never clips
    const limit = ctx.createDynamicsCompressor();
    limit.threshold.value = -6;
    limit.ratio.value = 8;
    master.connect(limit).connect(ctx.destination);
    noise = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) {
      data[i] = Math.random() * 2 - 1;
    }
  }
  if (ctx.state === "suspended") {
    ctx.resume().catch(() => {});
  }
}
window.addEventListener("pointerdown", wake, true);

function setSound(patch) {
  Object.assign(sound, patch);
  save(ON_KEY, sound.on ? "on" : "off");
  save(VOLUME_KEY, String(sound.volume));
  if (master) {
    master.gain.value = sound.volume;
  }
}

const rand = (lo, hi) => lo + Math.random() * (hi - lo);
// a little different every time, as a real tile is
const vary = (x, by) => x * (1 + rand(-by, by));

// a pitched partial that dies away, `at` seconds from now
function tone({at = 0, f, to, d, g, a = 0.002, type = "sine"}) {
  const t = ctx.currentTime + 0.01 + at;
  const osc = ctx.createOscillator();
  const env = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(f, t);
  if (to) {
    osc.frequency.exponentialRampToValueAtTime(to, t + a + d);
  }
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(Math.max(g, 0.0002), t + a);
  env.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
  osc.connect(env).connect(master);
  osc.start(t);
  osc.stop(t + a + d + 0.05);
}

// a burst of filtered noise: the contact of a tile, which has no pitch
function click({at = 0, d, g, f, q}) {
  const t = ctx.currentTime + 0.01 + at;
  const src = ctx.createBufferSource();
  const filter = ctx.createBiquadFilter();
  const env = ctx.createGain();
  src.buffer = noise;
  filter.type = "bandpass";
  filter.frequency.value = f;
  filter.Q.value = q;
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(g, t + 0.002);
  env.gain.exponentialRampToValueAtTime(0.0001, t + 0.002 + d);
  src.connect(filter).connect(env).connect(master);
  src.start(t, rand(0, 1.5));
  src.stop(t + d + 0.05);
}

// A mahjong tile striking the table (or, `onTile`, another tile) at strength `s`: a
// click, the tile ringing in a few inharmonic partials, and the table's thump.
function clack(at = 0, s = 1, {onTile = false, pitch = 1} = {}) {
  const p = vary(pitch, 0.05) * (onTile ? 1.18 : 1);
  s = vary(s, 0.1);
  click({at, d: 0.01, g: 0.55 * s, f: 3600 * p, q: 1.3});
  for (const [ratio, d, g] of [[1, 0.05, 0.22], [1.52, 0.032, 0.12], [2.41, 0.018, 0.07]]) {
    tone({at, f: 2350 * ratio * p, d: d * (0.7 + 0.4 * s), g: g * s});
  }
  if (!onTile) {
    tone({at, f: 165 * p, to: 115 * p, d: 0.045, g: 0.28 * s});
  }
}

// a soft mallet note, for the few things that aren't tiles
function note(f, at = 0, g = 0.14, d = 0.4) {
  tone({at, f, d, g, a: 0.006});
  tone({at, f: f * 4, d: 0.04, g: g * 0.12});
}

const [A4, E5, A5] = [0, 7, 12].map((n) => 440 * 2 ** (n / 12));

const SOUNDS = {
  // your tile picked up, to act with
  lift: () => clack(0, 0.25, {onTile: true, pitch: 1.3}),
  // a tile set down: every move, a tile pushed or pulled, one placed from a hand
  move: () => clack(0, 0.85),
  // a tile knocked over
  death: () => {
    clack(0, 1.05);
    clack(0.07, 0.6, {onTile: true});
  },
  flip: () => clack(0, 0.4, {onTile: true, pitch: 1.3}),
  exchange: () => {
    clack(0, 0.4, {onTile: true, pitch: 1.3});
    clack(0.12, 0.6, {onTile: true});
  },
  // one tile of the deal landing
  deal: () => clack(0, 0.5),
  // they've claimed, and you're to accept or challenge; also an opponent sitting down
  attention: () => {
    note(E5);
    note(A5, 0.11);
  },
  start: () => {
    note(A4);
    note(E5, 0.12);
  },
  end: () => {
    note(E5);
    note(A4, 0.13, 0.14, 0.6);
  },
  // your reserve running low
  low: () => tone({f: 1500, d: 0.05, g: 0.12, type: "triangle"}),
};

// the same sound twice this close together is heard once: three tiles knocked back
// together are one clack, a blast's deaths one death
const ONCE_MS = 40;
const last = {};

// play a sound, `delay` ms from now
function play(name, delay = 0) {
  if (!sound.on || sound.volume === 0) {
    return;
  }
  const at = performance.now() + delay;
  if (Math.abs(at - (last[name] ?? -Infinity)) < ONCE_MS) {
    return;
  }
  last[name] = at;
  window.setTimeout(() => {
    wake();
    if (ctx?.state === "running") {
      SOUNDS[name]();
    }
  }, delay);
}

export {sound, setSound, play, wake};
