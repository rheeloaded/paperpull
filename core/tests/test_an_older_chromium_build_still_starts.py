"""A browser starts with only an older Chromium build on disk, in real browsers.

An install upgraded from 0.59.1 (Playwright 1.63.0, build 1243) to 0.59.2
(1.64.1, build 1248) can hold only build 1243. A launch that names no
executable_path asks for the build the installed Playwright was made for,
so every app's own browser and the receipt renderer failed there with
"Executable doesn't exist" (test_every_launch_takes_a_chromium_on_disk.py
holds every launch to the fix with stand-ins).

Here the Chromium installed for this Playwright is laid out again as build
1000 in a folder of the test's own, hard links where the disk allows and
copies where it does not, never a junction or a symlink to a folder, so
removing the test's folder never reaches the real one. Playwright, told to
keep its browsers there, asks for its own build, which is not there.
Measured on 2026-10-30, Playwright 1.64.1 drove builds 1234 and 1228
(Chrome 151 and 149) each of these ways too. Every value here is made up.
"""
import os
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from paperpull_core import browser, receipt_pdf


@pytest.fixture(scope="module")
def own_build():
    """(chromium-<build>, chromium_headless_shell-<build>, where each one's
    executable is inside it) for the Playwright installed here, the
    folders it starts a browser from."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        own = Path(p.chromium.executable_path)
    folder = next((f for f in own.parents if re.fullmatch(r"chromium-\d+", f.name)), None)
    if folder is None or not own.is_file():
        pytest.skip("this Playwright's own Chromium is not installed here")
    shell = folder.with_name(folder.name.replace("chromium-", "chromium_headless_shell-"))
    shells = [f for f in shell.rglob("*") if f.is_file() and f.name in (
        "chrome-headless-shell.exe", "chrome-headless-shell", "headless_shell.exe", "headless_shell")]
    if len(shells) != 1:
        pytest.skip("this Playwright's own headless shell is not installed here")
    return folder, shell, own.relative_to(folder), shells[0].relative_to(shell)


def _lay_out_again(source: Path, target: Path) -> None:
    """source's files at target, each a hard link or else a copy. A link
    inside a macOS app bundle is made again as the same link."""
    for folder, dirs, files in os.walk(source):
        here = target / Path(folder).relative_to(source)
        here.mkdir(parents=True, exist_ok=True)
        for name in list(dirs) + files:
            src, dst = Path(folder) / name, here / name
            if src.is_symlink():
                os.symlink(os.readlink(src), dst, target_is_directory=src.is_dir())
                if name in dirs:
                    dirs.remove(name)
            elif name in files:
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)


@pytest.fixture
def only_build_1000(own_build, tmp_path, monkeypatch):
    """This Playwright's own Chromium and headless shell as build 1000,
    and nothing else, where Playwright is told to keep its browsers.
    Returns (that folder, build 1000's executable, its headless shell's)."""
    folder, shell, full_inner, shell_inner = own_build
    root = tmp_path / "ms-playwright"
    _lay_out_again(folder, root / "chromium-1000")
    _lay_out_again(shell, root / "chromium_headless_shell-1000")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    monkeypatch.setattr(browser, "_SAID_ON_DISK", set(), raising=False)
    return (root, root / "chromium-1000" / full_inner,
            root / "chromium_headless_shell-1000" / shell_inner)


@pytest.fixture
def handed(monkeypatch):
    """The executable_path each launch was handed, read where it starts."""
    seen = []
    real = browser._started

    def started(launch, *args, **kwargs):
        seen.append(kwargs.get("executable_path"))
        return real(launch, *args, **kwargs)
    monkeypatch.setattr(browser, "_started", started)
    return seen


def _playwright():
    """A Playwright of its own, started after the test has told it where
    its browsers are."""
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def test_playwright_alone_cannot_start_its_own_build_there(only_build_1000):
    """What every app's own browser and the renderer met."""
    root, _full, _shell = only_build_1000
    with _playwright() as p:
        assert Path(p.chromium.executable_path).is_relative_to(root)
        assert not Path(p.chromium.executable_path).exists()
        with pytest.raises(Exception, match="Executable doesn't exist"):
            p.chromium.launch(headless=True)


def test_an_apps_own_browser_starts_the_older_build(only_build_1000, handed, tmp_path, capsys):
    """Headless here only so no window opens during the tests, with the
    headless shell taken away, so the full build is the one started."""
    root, full, _shell = only_build_1000
    shutil.rmtree(root / "chromium_headless_shell-1000")
    with _playwright() as p:
        ctx = browser.launch_own_browser(p.chromium, str(tmp_path / "browser-profile"),
                                         headless=True, accept_downloads=True,
                                         viewport={"width": 1400, "height": 950})
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_content("<h1>Started</h1>")
            assert page.inner_text("h1") == "Started"
        finally:
            ctx.close()
    assert handed == [str(full)]
    assert "build 1000, the newest one here, is started instead" in capsys.readouterr().out


class _Receipt(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<title>Order 4417</title><h1>Receipt 4417 total 12.34</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def receipt_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Receipt)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


def test_the_receipt_renderer_prints_with_the_older_headless_shell(only_build_1000, handed,
                                                                    receipt_site, tmp_path):
    _root, _full, shell = only_build_1000
    out = tmp_path / "receipt.pdf"
    with _playwright() as p:
        receipt_pdf.render_url_headless(
            p, {"cookies": [], "origins": []}, receipt_site + "/receipt", out, wait_ms=0,
            is_safe_url=lambda u: str(u).startswith(receipt_site + "/"), hosts=("127.0.0.1",))
    assert handed == [str(shell)]
    data = out.read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 1000
