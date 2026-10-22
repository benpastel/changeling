"use strict";

// This browser's settings, opened from the corner: whether tiles and buttons describe
// themselves on hover, the dark theme, and whatever else main.js adds.  The theme is also set before the page is
// drawn, by a line in each page's head, so it never flashes light.

const TOOLTIPS_KEY = "arena.tooltips";
const THEME_KEY = "arena.theme";

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

// the corner button, and the panel it opens above itself; `more` are other switches,
// each [label, () => on, (on) => {}]
function setUpSettings(button, panel, more = []) {
  applyTheme();
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
    ...more.map(([label, on, change]) => toggle(label, on(), change)),
  );
  // those can change meanwhile, so they're looked at again on opening
  const others = [...panel.querySelectorAll("input")].slice(2);
  button.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    others.forEach((input, i) => {
      input.checked = more[i][1]();
    });
  });
  // anywhere else closes it
  document.addEventListener("click", ({ target }) => {
    if (!panel.hidden && !panel.contains(target) && !button.contains(target)) {
      panel.hidden = true;
    }
  });
  document.addEventListener("keydown", ({ key }) => {
    if (key === "Escape") {
      panel.hidden = true;
    }
  });
}

export {settings, setUpSettings};
