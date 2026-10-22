"""
The tutorial in a real browser, against the bot: every step of the intro, then the
first-time tips as a random game brings them up, in a spread of window sizes and both
themes.  Each note is held to how it should sit: inside the window, covering nothing it
points at or rings, with its pointer drawn at what it's about.  A screenshot of each is
kept in test/screens/tutorial for looking over.

Runs its own page and game servers, so it needs playwright's chromium (`uv run
playwright install chromium`); it's skipped without it.
"""

import json
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "test" / "screens" / "tutorial"

SIZES = [(1280, 800), (1440, 900), (1024, 768), (1920, 1080), (820, 1100)]
THEMES = ["light", "dark"]

# how far the card sits from what it points at, and how far its pointer reaches across
# that (see guide.js); and how far the tip may be from where it should be
GAP = 14
REACH = 9
SLACK = 3


def _free_pair() -> int:
    """A port for the page whose next port is free too, for the game (see net.js)."""
    for _ in range(50):
        port = random.randrange(20000, 40000)
        try:
            for p in (port, port + 1):
                with socket.socket() as s:
                    s.bind(("localhost", p))
            return port
        except OSError:
            continue
    raise RuntimeError("no free ports")


def _wait_for(port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"nothing listening on {port}")


@pytest.fixture(scope="module")
def site():
    port = _free_pair()
    page = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", "docs"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    game = subprocess.Popen(
        [sys.executable, "-m", "server.app"],
        cwd=ROOT,
        env={**os.environ, "PORT": str(port + 1), "BOT_DELAY": "0.01"},
        stdout=subprocess.DEVNULL,
    )
    try:
        _wait_for(port)
        _wait_for(port + 1)
        yield f"http://localhost:{port}/"
    finally:
        page.terminate()
        game.terminate()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except Exception as e:  # no browser installed
            pytest.skip(f"no chromium: {e}")
        yield launched
        launched.close()


# everything about the note showing, measured in the page: the card, its pointer's
# tip as drawn, the rings, what it points at, and the window
MEASURE = """() => {
  const root = document.querySelector(".guide");
  const card = root.querySelector(".guide-card");
  const box = (r) => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom});
  const rect = box(card.getBoundingClientRect());
  const side = ["above", "below", "left", "right"].find((s) => card.classList.contains(s)) ?? null;
  let tip = null;
  if (side) {
    // the pointer is a bordered square turned 45°: its far corner is the tip
    const after = getComputedStyle(card, "::after");
    const border = parseFloat(getComputedStyle(card).borderLeftWidth);
    const size = parseFloat(after.width) + parseFloat(after.borderRightWidth);
    const half = (size * Math.SQRT2) / 2;
    const px = (v) => parseFloat(v);
    let cx, cy;
    if (side === "above" || side === "below") {
      cx = rect.left + border + px(after.left) + size / 2;
      cy = side === "below" ? rect.top + border + px(after.top) + size / 2
                            : rect.bottom - border - px(after.bottom) - size / 2;
    } else {
      cy = rect.top + border + px(after.top) + size / 2;
      cx = side === "right" ? rect.left + border + px(after.left) + size / 2
                            : rect.right - border - px(after.right) - size / 2;
    }
    const out = {above: [0, 1], below: [0, -1], left: [1, 0], right: [-1, 0]}[side];
    tip = {x: cx + out[0] * half, y: cy + out[1] * half};
  }
  const rings = [...root.querySelectorAll(".guide-ring")].map((r) => box(r.getBoundingClientRect()));
  return {
    card: rect, side, tip, rings,
    target: JSON.parse(root.dataset.target || "null"),
    targets: JSON.parse(root.dataset.targets || "[]"),
    dim: root.classList.contains("dim"),
    text: card.querySelector(".guide-text").textContent,
    window: {width: innerWidth, height: innerHeight},
  };
}"""


def _overlap(a: dict, b: dict) -> float:
    width = min(a["right"], b["right"]) - max(a["left"], b["left"])
    height = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    return width * height if width > 0 and height > 0 else 0


def check_note(page, name: str) -> dict:
    """Hold the showing note to how it should sit, and keep a picture of it."""
    # let it settle where it's going (it lays out on the next frame)
    page.wait_for_timeout(120)
    note = page.evaluate(MEASURE)
    SCREENS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=SCREENS / f"{name}.png")
    where = f"{name}: {note['text']!r}"

    card, target, window = note["card"], note["target"], note["window"]
    assert card["left"] >= 0 and card["top"] >= 0, where
    assert (
        card["right"] <= window["width"] and card["bottom"] <= window["height"]
    ), where
    assert target is not None, f"{where} points at nothing"
    assert target["right"] > target["left"] and target["bottom"] > target["top"], where
    for pointed in note["targets"]:
        assert _overlap(card, pointed) == 0, f"{where} covers what it points at"
    for ring in note["rings"]:
        assert _overlap(card, ring) == 0, f"{where} covers a ring"
        assert ring["left"] >= 0 and ring["top"] >= 0, f"{where} ring off the window"
        assert ring["right"] <= window["width"], f"{where} ring off the window"
        assert ring["bottom"] <= window["height"], f"{where} ring off the window"

    # the pointer's tip is just off the target, facing it, within its span
    assert note["side"] is not None, where
    x, y = note["tip"]["x"], note["tip"]["y"]
    if note["side"] in ("above", "below"):
        assert target["left"] < x < target["right"], f"{where} pointer misses across"
        gap = target["top"] - y if note["side"] == "above" else y - target["bottom"]
    else:
        assert target["top"] < y < target["bottom"], f"{where} pointer misses along"
        gap = target["left"] - x if note["side"] == "left" else x - target["right"]
    assert 0 <= gap <= GAP - REACH + SLACK, f"{where} pointer is {gap:.1f}px off"
    return note


def _new_game(
    browser, site: str, size, theme: str, tutorial: dict | None, time_mode=None
):
    context = browser.new_context(viewport={"width": size[0], "height": size[1]})
    init = f"localStorage.setItem('arena.theme', '{theme}');"
    if tutorial is not None:
        init += f"localStorage.setItem('arena.tutorial', '{json.dumps(tutorial)}');"
    # only once, so the page's own saves stick across its reloads
    context.add_init_script(
        f"if (!sessionStorage.getItem('seeded')) {{ {init} sessionStorage.setItem('seeded', '1'); }}"
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(site)
    page.fill(".name-input", "tester")
    page.click(".play-bot")
    page.wait_for_selector(".room-foot .primary")
    if time_mode:
        page.click(f".time-area button:has-text('{time_mode}')")
        page.wait_for_selector(f".time-area button.on:has-text('{time_mode}')")
    page.click(".room-foot .primary")
    page.wait_for_selector("body.at-game")
    return context, page, errors


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_every_step_of_the_intro(browser, site, size, theme):
    context, page, errors = _new_game(browser, site, size, theme, None)
    page.wait_for_selector(".guide.dim .guide-card")
    texts = []
    step = 0
    while True:
        note = check_note(page, f"intro-{size[0]}x{size[1]}-{theme}-{step + 1}")
        assert note["dim"]
        texts.append(note["text"])
        # nothing has happened in the game meanwhile
        assert page.locator(".log-item").count() == 0
        primary = page.locator(".guide-primary")
        last = primary.text_content() == "play"
        primary.click()
        step += 1
        if last:
            break
        page.wait_for_function(
            "(previous) => document.querySelector('.guide-text')?.textContent !== previous",
            arg=note["text"],
        )
    assert len(set(texts)) == step >= 2
    page.wait_for_selector(".guide", state="hidden")
    saved = json.loads(page.evaluate("localStorage.getItem('arena.tutorial')"))
    assert saved["intro"] is True

    # once played through, a new page doesn't show it again
    page.reload()
    page.wait_for_selector("body.at-game")
    page.wait_for_timeout(500)
    assert not page.locator(".guide.dim").is_visible()
    assert errors == []
    context.close()


def test_the_intro_pauses_the_clock_and_can_be_ended(browser, site):
    context, page, errors = _new_game(
        browser, site, (1280, 800), "light", None, time_mode="fast"
    )
    page.wait_for_selector(".guide.dim .guide-card")
    page.wait_for_timeout(300)
    clocks = page.locator(".strip .clock").all_text_contents()
    page.wait_for_timeout(1600)
    assert page.locator(".strip .clock").all_text_contents() == clocks

    # ending it straight away, from the keyboard, resumes the game
    page.keyboard.press("Escape")
    page.wait_for_selector(".guide", state="hidden")
    page.wait_for_timeout(1600)
    assert page.locator(".strip .clock").all_text_contents() != clocks
    assert errors == []
    context.close()


def test_the_opponent_sees_the_pause(browser, site):
    # the host has played before; the guest hasn't, so the match waits for them
    done = {"intro": True, "seen": [], "off": True}
    pages = []
    for name, tutorial in [("host", done), ("guest", None)]:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        if tutorial is not None:
            context.add_init_script(
                f"localStorage.setItem('arena.tutorial', '{json.dumps(tutorial)}')"
            )
        page = context.new_page()
        page.goto(site)
        page.fill(".name-input", name)
        pages.append((context, page))
    (host_context, host), (guest_context, guest) = pages
    host.click(".new-table")
    host.wait_for_selector(".room-foot .primary")
    guest.goto(host.url)
    guest.wait_for_selector(".room")
    host.wait_for_selector(".room-foot .primary:not([disabled])")
    host.click(".room-foot .primary")

    guest.wait_for_selector(".guide.dim .guide-card")
    host.wait_for_function(
        "document.querySelector('.strip.top .turn-note')?.textContent === 'paused'"
    )
    # the host moves first, and can make their move, but it doesn't happen until the
    # guest is through
    host.click(".board .cell.highlight.own-piece", position={"x": 4, "y": 4})
    # a move is drawn in the square it goes to
    host.locator(".board .option[data-name='↕']").first.click()
    host.wait_for_timeout(600)
    assert host.locator(".log-item").count() == 0
    guest.keyboard.press("Escape")
    host.wait_for_function(
        "document.querySelector('.strip.top .turn-note')?.textContent !== 'paused'"
    )
    host.wait_for_selector(".log-item")
    host_context.close()
    guest_context.close()


def _play_a_move(page, rng: random.Random) -> None:
    """Click something the game is offering, if anything."""
    if page.is_visible(".next-game"):
        page.click(".next-game")
        return
    options = page.query_selector_all(".board .choice-panel .option")
    options = options or page.query_selector_all(".board .option")
    if options:
        rng.choice(options).click()
        return
    squares = page.query_selector_all(".board .cell.highlight")
    if squares:
        try:
            rng.choice(squares).click(position={"x": 4, "y": 4})
        except Exception:
            pass


@pytest.mark.parametrize(
    "size,theme",
    [((1280, 800), "light"), ((1024, 768), "dark"), ((820, 1100), "light")],
    ids=["1280x800-light", "1024x768-dark", "820x1100-light"],
)
def test_tips_as_they_come_up(browser, site, size, theme):
    context, page, errors = _new_game(
        browser, site, size, theme, {"intro": True, "seen": [], "off": False}
    )
    rng = random.Random(f"{size}{theme}")
    shown: list[str] = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and len(shown) < 5:
        if page.is_visible(".guide .guide-card"):
            note = check_note(page, f"tip-{size[0]}x{size[1]}-{theme}-{len(shown) + 1}")
            assert not note["dim"]
            shown.append(note["text"])
            page.click(".guide-primary")
            page.wait_for_timeout(50)
            continue
        _play_a_move(page, rng)
        page.wait_for_timeout(40)
    # answering a claim comes up in any game, and others besides
    assert len(set(shown)) >= 2, shown
    seen = json.loads(page.evaluate("localStorage.getItem('arena.tutorial')"))["seen"]
    assert len(seen) >= len(set(shown))
    assert errors == []
    context.close()
