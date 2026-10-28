"""
The deal at the start of a game, in a browser (see animate.js): every tile flies out
from a pile on the board to where it's dealt, clacking as it lands, unless the
setting's off. 
"""

import pytest

pytest.importorskip("playwright.sync_api")

from test.browsing import new_game  # noqa: E402

NO_TUTORIAL = {"intro": True, "seen": [], "off": True}

# the places a tile is dealt to
DEALT = (
    ".board .piece, .strip .hand-tile, .board .exchange .cell-marks .board-tile,"
    " .unused-contents .acc-tile"
)

# counts the sounds' oscillators, to know the clacks were played
COUNT_SOUNDS = """
window.oscillators = 0;
const make = AudioContext.prototype.createOscillator;
AudioContext.prototype.createOscillator = function () {
  window.oscillators += 1;
  return make.call(this);
};
"""


def _start(browser, site, deal: bool):
    return new_game(
        browser,
        site,
        (1280, 800),
        "light",
        NO_TUTORIAL,
        storage={"arena.deal": "on" if deal else "off"},
        script=COUNT_SOUNDS,
    )


def test_a_new_game_is_dealt(browser, site):
    context, page, errors = _start(browser, site, deal=True)
    page.wait_for_selector(".ghost")
    dealt = page.locator(DEALT).count()
    assert page.locator(".ghost").count() == dealt
    # done in about a second, every tile showing where it was dealt
    page.wait_for_selector(".ghost", state="detached", timeout=2000)
    hidden = page.evaluate(
        f"""() => [...document.querySelectorAll({DEALT!r})]
          .filter((tile) => tile.getAnimations().length > 0).length"""
    )
    assert hidden == 0
    assert page.evaluate("window.oscillators") >= dealt
    assert errors == []
    context.close()


def test_the_deal_can_be_turned_off(browser, site):
    context, page, errors = _start(browser, site, deal=False)
    page.wait_for_selector(".board .piece")
    page.wait_for_timeout(300)
    assert page.locator(".ghost").count() == 0
    assert errors == []
    context.close()
