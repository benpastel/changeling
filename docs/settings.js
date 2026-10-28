"use strict";

// This browser's settings, from the top-left corner on every screen, as in wordbreak:
// sound on or off; the sliders, which open the rest (tooltips on hover, the dark
// theme, the volume, and whatever main.js adds); and full screen.  The theme is also
// set before the page is drawn, by a line in each page's head, so it never flashes light.

import {sound, setSound, play, wake} from "./sound.js";

const TOOLTIPS_KEY = "arena.tooltips";
const THEME_KEY = "arena.theme";
const DEAL_KEY = "arena.deal";

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

const settings = {
  tooltips: load(TOOLTIPS_KEY) !== "off",
  dark: load(THEME_KEY) === "dark",
  // each game starts with its tiles dealt out (see animate.js)
  deal: load(DEAL_KEY) !== "off",
};

function applyTheme() {
  document.documentElement.dataset.theme = settings.dark ? "dark" : "light";
}

// a labelled switch, on or off
function toggle(label, on, change) {
  const row = document.createElement("label");
  row.className = "setting";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = on;
  input.addEventListener("change", () => change(input.checked));
  const name = document.createElement("span");
  name.textContent = label;
  const track = document.createElement("span");
  track.className = "switch";
  row.append(name, input, track);
  return row;
}

const ICONS = {
  soundOn:
    '<path d="M3 7.5h3l4-3.5v12l-4-3.5H3z" fill="currentColor"/>' +
    '<path d="M13 7.5a3.5 3.5 0 0 1 0 5M15.2 5.3a6.6 6.6 0 0 1 0 9.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  soundOff:
    '<path d="M3 7.5h3l4-3.5v12l-4-3.5H3z" fill="currentColor"/>' +
    '<path d="M13 8l4 4M17 8l-4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  sliders:
    '<path d="M3 6h14M3 14h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>' +
    '<circle cx="7" cy="6" r="2.6" fill="currentColor"/><circle cx="13" cy="14" r="2.6" fill="currentColor"/>',
  full:
    '<path d="M3 7.5V3h4.5M17 7.5V3h-4.5M3 12.5V17h4.5M17 12.5V17h-4.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
  leave:
    '<path d="M7.5 3v4.5H3M12.5 3v4.5H17M7.5 17v-4.5H3M12.5 17v-4.5H17" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
};

function iconButton(className, label) {
  const button = document.createElement("button");
  button.className = `corner-button ${className}`;
  button.setAttribute("aria-label", label);
  return button;
}

function setIcon(button, icon) {
  button.innerHTML = `<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">${ICONS[icon]}</svg>`;
}

// Full screen; Safari on iPad still uses the webkit names, and iPhone has none for a
// page, so there the button isn't shown
const canFullscreen = Boolean(document.fullscreenEnabled || document.webkitFullscreenEnabled);
const isFullscreen = () => Boolean(document.fullscreenElement || document.webkitFullscreenElement);

function toggleFullscreen() {
  if (isFullscreen()) {
    (document.exitFullscreen ?? document.webkitExitFullscreen)?.call(document);
  } else {
    const root = document.documentElement;
    const request = root.requestFullscreen?.({navigationUI: "hide"}) ?? root.webkitRequestFullscreen?.();
    request?.catch?.(() => {});
  }
}

// the corner's buttons, and the panel the sliders open below them; `more` are other
// switches, each [label, () => on, (on) => {}]
function setUpSettings(corner, more = []) {
  applyTheme();

  const soundButton = iconButton("sound", "sound");
  const showSound = () => {
    setIcon(soundButton, sound.on ? "soundOn" : "soundOff");
    soundButton.setAttribute("aria-pressed", sound.on);
  };
  showSound();
  // switching on is itself a click, which is what browsers want before any sound
  soundButton.addEventListener("click", () => {
    setSound({on: !sound.on});
    wake();
    showSound();
  });

  const slidersButton = iconButton("sliders", "settings");
  setIcon(slidersButton, "sliders");
  slidersButton.setAttribute("aria-expanded", "false");

  const fullButton = iconButton("full", "full screen");
  const showFull = () => setIcon(fullButton, isFullscreen() ? "leave" : "full");
  showFull();
  fullButton.addEventListener("click", toggleFullscreen);
  // the browser also leaves full screen on Escape, without the button
  document.addEventListener("fullscreenchange", showFull);
  document.addEventListener("webkitfullscreenchange", showFull);
  fullButton.hidden = !canFullscreen;

  const panel = document.createElement("div");
  panel.className = "settings";
  panel.hidden = true;

  const volume = document.createElement("label");
  volume.className = "setting volume";
  const volumeName = document.createElement("span");
  volumeName.textContent = "volume";
  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = "0";
  slider.max = "1";
  slider.step = "0.05";
  slider.value = String(sound.volume);
  slider.addEventListener("input", () => setSound({volume: Number(slider.value)}));
  // a clack at the new volume, on letting go
  slider.addEventListener("change", () => play("move"));
  volume.append(volumeName, slider);

  panel.append(
    toggle("tooltips", settings.tooltips, (on) => {
      settings.tooltips = on;
      save(TOOLTIPS_KEY, on ? "on" : "off");
    }),
    toggle("dark mode", settings.dark, (on) => {
      settings.dark = on;
      save(THEME_KEY, on ? "dark" : "light");
      applyTheme();
    }),
    toggle("dealing", settings.deal, (on) => {
      settings.deal = on;
      save(DEAL_KEY, on ? "on" : "off");
    }),
    ...more.map(([label, on, change]) => toggle(label, on(), change)),
    volume,
  );
  corner.append(soundButton, slidersButton, fullButton, panel);

  // those can change meanwhile, so they're looked at again on opening
  const others = [...panel.querySelectorAll("input[type=checkbox]")].slice(3);
  const open = (on) => {
    panel.hidden = !on;
    slidersButton.setAttribute("aria-expanded", String(on));
  };
  slidersButton.addEventListener("click", () => {
    open(panel.hidden);
    others.forEach((input, i) => {
      input.checked = more[i][1]();
    });
  });
  // anywhere else closes it
  document.addEventListener("click", ({target}) => {
    if (!panel.hidden && !corner.contains(target)) {
      open(false);
    }
  });
  document.addEventListener("keydown", ({key}) => {
    if (key === "Escape") {
      open(false);
    }
  });
}

export {settings, setUpSettings};
