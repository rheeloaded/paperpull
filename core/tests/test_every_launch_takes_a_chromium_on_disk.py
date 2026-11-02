"""Every browser an app or the core starts takes a Chromium that is on disk.

A launch that names no executable_path starts the Chromium build the
installed Playwright was made for. Each Playwright upgrade brings a new
build, and an install upgraded from 0.59.1 (Playwright 1.63.0, build 1243)
to 0.59.2 (1.64.1, build 1248) can hold only build 1243, since the packages
carry no Chromium and nothing downloads the new build. Every app's own
browser (a config with no cdp_url) and the receipt renderer then failed
with "Executable doesn't exist", while the download was never offered,
because a build was on disk.

Both now start through browser.sandboxed_launch and
sandboxed_persistent_context, which hand such a launch the newest build on
disk (_on_disk), and test_every_browser_starts_in_its_sandbox.py holds
every launch to those two. This drives each app's own run, built the way
its command line builds it with no cdp_url, and the renderer, against a
Playwright made for build 1248 with only build 1243 on disk, and reads
every file that ships for a launch it does not drive. Every value here is
made up, and no browser is started.
"""
import ast
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from paperpull_core import browser

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_every_app_downloads_again_when_the_panel_asks as apps  # noqa: E402
import test_every_browser_starts_in_its_sandbox as sandbox  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# The core's ways to start a browser. Every launch goes through one of them
# (test_every_browser_starts_in_its_sandbox).
STARTS = frozenset(("launch_own_browser", "sandboxed_launch", "sandboxed_persistent_context"))

# Where Playwright unpacks build 1243 and its headless shell on this
# machine's platform, as 1.57 and later do.
INNER = {
    "win32": ("chrome-win64/chrome.exe",
              "chrome-headless-shell-win64/chrome-headless-shell.exe"),
    "darwin": ("chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/"
               "Google Chrome for Testing",
               "chrome-headless-shell-mac-arm64/chrome-headless-shell"),
    "linux": ("chrome-linux64/chrome", "chrome-headless-shell-linux64/chrome-headless-shell"),
}


def _starts_in(path: Path) -> list:
    """(function, what it calls) for every call of one of STARTS in path,
    the function being the innermost one around it."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    owner = sandbox._enclosing_functions(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in STARTS:
                out.append((owner.get(id(node)), name))
    return out


def _own_browser_apps() -> list:
    """Every app whose run opens a browser of its own, the folder with the
    module its command line runs."""
    out = []
    for folder in apps.FOLDERS:
        found = apps.entries(folder)
        if found and ("browser", "launch_own_browser") in _starts_in(found[0][0]):
            out.append(folder)
    return out


OWN_BROWSER_APPS = _own_browser_apps()


class _Stopped(Exception):
    """Raised by the stand-in once a launch it was asked for is noted."""


class _Chromium:
    """Playwright's browser type as a stand-in, made for build 1248 at
    `own`, noting what each launch is handed."""

    def __init__(self, own, stop=False):
        self.executable_path = str(own)
        self.asked = []
        self.stop = stop

    def launch(self, **kwargs):
        self.asked.append(("launch", kwargs))
        if self.stop:
            raise _Stopped()
        return mock.MagicMock()

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.asked.append(("persistent", kwargs))
        return mock.MagicMock()


class _Playwright:
    """What sync_playwright() hands back, started and stopped."""

    def __init__(self, chromium):
        self.chromium = chromium

    def start(self):
        return self

    def stop(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def only_build_1243(tmp_path, monkeypatch):
    """Build 1243 and its headless shell, each marked complete, in the
    folder Playwright keeps its browsers in, and a Playwright made for
    1248. No browser of the person's own is looked for. Returns (that
    Playwright's browser type, build 1243, its headless shell)."""
    full, shell = INNER.get(sys.platform, INNER["linux"])
    root = tmp_path / "ms-playwright"
    for folder, inner in (("chromium-1243", full), ("chromium_headless_shell-1243", shell)):
        exe = root / folder / inner
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        (root / folder / "INSTALLATION_COMPLETE").write_text("")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(root))
    monkeypatch.setattr(browser, "_real_browsers", lambda: [])
    monkeypatch.setattr(browser, "_SAID_ON_DISK", set(), raising=False)
    chromium = _Chromium(root / "chromium-1248" / full)
    sync_api = pytest.importorskip("playwright.sync_api")
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: _Playwright(chromium))
    return chromium, root / "chromium-1243" / full, root / "chromium_headless_shell-1243" / shell


def _built(folder: Path, mod, parser_fn: str, cls: str, home: Path):
    """The app, built the way its command line builds it for the panel's
    Pilot, from a config that names no cdp_url."""
    example = folder / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({
        "owner": "Dana Example", "output_dir": str(home / "out"),
        "profile_dir": str(home / "profile"), "cdp_url": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
    })
    home.mkdir(parents=True, exist_ok=True)
    cfg = home / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    argv = apps.panel_argv("pilot", apps.SCOPES[0], again=False) + ["--config", str(cfg)]
    return getattr(mod, cls)(getattr(mod, parser_fn)().parse_args(argv))


@pytest.mark.parametrize("folder", OWN_BROWSER_APPS, ids=lambda d: d.name)
def test_every_apps_own_browser_takes_the_build_on_disk(folder, only_build_1243, tmp_path,
                                                        monkeypatch):
    chromium, full, _shell = only_build_1243
    module, parser_fn, cls = apps.entries(folder)[0]
    mod = apps.load(folder, module)
    monkeypatch.setattr(mod, "sync_playwright", lambda: _Playwright(chromium), raising=False)
    inst = _built(folder, mod, parser_fn, cls, tmp_path / "app")
    inst.browser()
    assert [(how, kw.get("executable_path"), kw.get("headless")) for how, kw in chromium.asked] \
        == [("persistent", str(full), False)], (
        "%s's own browser was not handed build 1243, the only one on disk" % folder.name)


def test_the_receipt_renderer_takes_the_headless_shell_on_disk(only_build_1243, tmp_path):
    from paperpull_core import receipt_pdf
    chromium, _full, shell = only_build_1243
    chromium.stop = True
    address = "https://shop.example/receipt/1"
    with pytest.raises(_Stopped):
        receipt_pdf.render_url_headless(
            _Playwright(chromium), {}, address, tmp_path / "out.pdf", wait_ms=0,
            is_safe_url=lambda u: str(u).startswith("https://shop.example/"),
            hosts=("shop.example",))
    assert [(how, kw.get("executable_path"), kw.get("headless")) for how, kw in chromium.asked] \
        == [("launch", str(shell), True)]


# Each launch outside browser.py and what drives it above. A new one fails
# test_every_launch_is_driven_here until it is driven too.
DRIVEN_IN_THE_CORE = {
    ("core/paperpull_core/receipt_pdf.py", "render_url_headless", "sandboxed_launch"):
        "test_the_receipt_renderer_takes_the_headless_shell_on_disk",
}

# The one place that names the browser it starts. Target hands its own
# browser the person's Edge or Chrome where the sign-in would put that
# first, found on disk by browser.find_browser, and nothing otherwise.
NAMES_ITS_BROWSER = {"apps/target/target_receipts.py"}


def test_every_launch_is_driven_here():
    driven = {module.relative_to(REPO).as_posix() for folder in OWN_BROWSER_APPS
              for module in [apps.entries(folder)[0][0]]}
    undriven, seen = [], set()
    for path in sandbox.SOURCES:
        rel = path.relative_to(REPO).as_posix()
        if rel == sandbox.BROWSER_PY:
            continue
        for fn, name in _starts_in(path):
            seen.add((rel, fn, name))
            if (rel, fn, name) in DRIVEN_IN_THE_CORE:
                continue
            if not (rel in driven and (fn, name) == ("browser", "launch_own_browser")):
                undriven.append("%s %s calls %s" % (rel, fn, name))
    assert not undriven, "these start a browser this census does not drive, %s" % undriven
    assert set(DRIVEN_IN_THE_CORE) <= seen, "a launch named above is gone or moved"


def test_only_target_names_the_browser_it_starts():
    """A launch handed an executable_path or a channel is left as it is,
    so every one has to be a browser found on disk."""
    naming = set()
    for path in sandbox.SOURCES:
        rel = path.relative_to(REPO).as_posix()
        if rel == sandbox.BROWSER_PY:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if (isinstance(node, ast.keyword) and node.arg in ("executable_path", "channel")) or (
                    isinstance(node, ast.Constant)
                    and node.value in ("executable_path", "executablePath", "channel")):
                naming.add(rel)
    assert naming == NAMES_ITS_BROWSER


def test_the_census_is_not_empty():
    """Found by what each app's code does, a census that finds nothing
    passes on nothing. Every app opens a browser of its own when its
    config names no cdp_url."""
    assert len(OWN_BROWSER_APPS) >= 78
    assert len(OWN_BROWSER_APPS) == len(apps.FOLDERS)
    assert any(f.name == "target" for f in OWN_BROWSER_APPS)
