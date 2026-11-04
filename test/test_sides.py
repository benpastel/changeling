"""
Both players agree on the colours, north red and south blue, while each sees the board
from their own side, theirs at the bottom.
"""

import json

import pytest

pytest.importorskip("playwright.sync_api")

DONE = {"intro": True, "seen": [], "off": True}

# each strip's side and colour, and the colour of each side's pieces on the board
COLOURS = """() => {
  const colour = (selector) => {
    const element = document.querySelector(selector);
    return element && getComputedStyle(element).color;
  };
  const strip = (where) => {
    const element = document.querySelector(`.strip.${where}`);
    const side = element.classList.contains("north") ? "north" : "south";
    return {side, colour: colour(`.strip.${where} .name`)};
  };
  return {
    top: strip("top"),
    bottom: strip("bottom"),
    north: colour(".board .cell.north .piece"),
    south: colour(".board .cell.south .piece"),
    red: getComputedStyle(document.documentElement).getPropertyValue("--red").trim(),
  };
}"""


def _rgb(hex_colour: str) -> str:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgb({r}, {g}, {b})"


def test_both_players_agree_on_the_colours(browser, site):
    pages = []
    for name in ["host", "guest"]:
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        context.add_init_script(
            f"localStorage.setItem('arena.tutorial', '{json.dumps(DONE)}')"
        )
        page = context.new_page()
        page.goto(site)
        page.fill(".name-input", name)
        pages.append((context, page))
    (_, host), (_, guest) = pages
    host.click(".new-table")
    host.wait_for_selector(".room-foot .primary")
    guest.goto(host.url)
    guest.wait_for_selector(".room")
    host.wait_for_selector(".room-foot .primary:not([disabled])")
    host.click(".room-foot .primary")

    seen = {}
    for name, page in [("host", host), ("guest", guest)]:
        page.wait_for_selector(".board .cell.north .piece")
        page.wait_for_selector(".board .cell.south .piece")
        seen[name] = page.evaluate(COLOURS)

    host_view, guest_view = seen["host"], seen["guest"]
    # each at the bottom of their own board, on opposite sides
    assert host_view["bottom"]["side"] != guest_view["bottom"]["side"]
    assert host_view["bottom"]["side"] == guest_view["top"]["side"]
    for view in (host_view, guest_view):
        red = _rgb(view["red"])
        assert view["north"] == red != view["south"]
        for where in ("top", "bottom"):
            strip = view[where]
            assert (strip["colour"] == red) == (strip["side"] == "north")
    # the same colours for both
    assert host_view["north"] == guest_view["north"]
    assert host_view["south"] == guest_view["south"]
    for context, _ in pages:
        context.close()
