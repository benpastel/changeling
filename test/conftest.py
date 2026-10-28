"""
A page server and a game server for the browser tests, with a fast bot, and a browser;
each module of tests gets its own.  They need playwright's chromium (`uv run playwright
install chromium`), and are skipped without it.
"""

import os
import random
import socket
import subprocess
import sys
import time

import pytest

from test.browsing import ROOT


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


def sync_api():
    return pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with sync_api().sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except Exception as e:  # no browser installed
            pytest.skip(f"no chromium: {e}")
        yield launched
        launched.close()
