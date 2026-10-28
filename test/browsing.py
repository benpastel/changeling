"""Starting a game in the browser tests (see conftest.py for the servers)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def new_game(
    browser,
    site: str,
    size,
    theme: str,
    tutorial: dict | None,
    time_mode=None,
    storage: dict | None = None,
    script: str = "",
):
    """A game against the bot, with `storage` (and the theme and tutorial) saved
    beforehand, and `script` run in the page before its own."""
    context = browser.new_context(viewport={"width": size[0], "height": size[1]})
    storage = {"arena.theme": theme, **(storage or {})}
    if tutorial is not None:
        storage["arena.tutorial"] = json.dumps(tutorial)
    init = "".join(
        f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});"
        for k, v in storage.items()
    )
    # only once, so the page's own saves stick across its reloads
    context.add_init_script(
        f"if (!sessionStorage.getItem('seeded')) {{ {init} sessionStorage.setItem('seeded', '1'); }}"
        + script
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
