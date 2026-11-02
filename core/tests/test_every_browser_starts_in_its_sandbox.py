"""Every browser Playwright starts here starts inside its sandbox.

Playwright 1.63's driver adds --no-sandbox to Chromium's command line
unless the launch is handed chromium_sandbox=True, exactly True. Every
app's own browser (a run whose config names no cdp_url, 75 app files) and
the headless receipt renderer were started without it, so a page in them
had nothing between it and this computer but the renderer itself. Both
now start through paperpull_core.browser's sandboxed_launch and
sandboxed_persistent_context, which always ask for the sandbox, refuse a
caller that asks for less, and refuse to start at all when the sandbox
cannot.

This reads every file that ships, the apps' own included and the tests
apart, and fails on a Playwright launch anywhere but those two, on a
chromium_sandbox keyword anywhere but the one place that sets it, and on a
switch that turns a sandbox off in any string. Then it starts real
browsers each way and reads their command lines from the processes
themselves. The sign-in browser is started by subprocess, never by
Playwright, and its command line is checked too.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from paperpull_core import browser

REPO = Path(__file__).resolve().parents[2]

# Playwright's ways to start a browser, rather than attach to one.
LAUNCHES = frozenset(("launch", "launch_persistent_context", "launch_server"))
WRAPPERS = frozenset(("sandboxed_launch", "sandboxed_persistent_context"))
BROWSER_PY = "core/paperpull_core/browser.py"

# What ships. The apps, the core, the panel, the server, the tools and the
# packaging, and the files at the top of the checkout.
ROOTS = ("apps", "core", "gui", "server", "tools", "packaging")
# Folders a build or an install makes, copies of what ships.
MADE_FOLDERS = {"build", "dist", "site-packages", "node_modules"}

# A switch on a command line, with one dash or two.
SWITCH = re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*(?:=[^\s\"',;)]*)?")


def is_test(path: Path) -> bool:
    parts = path.relative_to(REPO).parts
    return ("tests" in parts or path.name.startswith("test_")
            or path.name == "conftest.py" or ".venv" in parts
            or any(p.startswith(".") for p in parts))


def sources():
    out = sorted(REPO.glob("*.py"))
    for root in ROOTS:
        for folder, dirs, files in os.walk(REPO / root):
            dirs[:] = sorted(d for d in dirs if d != "tests" and d not in MADE_FOLDERS
                             and not d.startswith((".", "__")) and not d.endswith(".egg-info"))
            out.extend(Path(folder) / f for f in files if f.endswith(".py"))
    return sorted(p for p in out if not is_test(p))


def _enclosing_functions(tree) -> dict:
    """Each node's innermost enclosing function name, by id."""
    owner = {}

    def visit(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            owner[id(child)] = name
            visit(child, name)
    visit(tree, None)
    return owner


def unsandboxed(source: str, rel: str = "x.py") -> list:
    """Every way `source` could start a browser outside the wrappers, or
    with less than its sandbox, as (line, what) pairs."""
    tree = ast.parse(source)
    owner = _enclosing_functions(tree)
    in_browser_py = rel == BROWSER_PY
    out = []
    for node in ast.walk(tree):
        fn = owner.get(id(node))
        if isinstance(node, ast.Attribute) and node.attr in LAUNCHES:
            if not (in_browser_py and fn in WRAPPERS):
                out.append((node.lineno, "Playwright %s" % node.attr))
        if isinstance(node, ast.Call):
            for k in node.keywords:
                if k.arg == "chromium_sandbox" and not (in_browser_py and fn == "_sandboxed"):
                    out.append((node.lineno, "chromium_sandbox given"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A launch named in a string, for getattr or a table of names,
            # and the sandbox keyword spread in from a dict.
            if node.value in LAUNCHES:
                out.append((node.lineno, "Playwright %s by name" % node.value))
            if node.value in ("chromium_sandbox", "chromiumSandbox") and not (
                    in_browser_py and fn == "_sandboxed"):
                out.append((node.lineno, "%s by name" % node.value))
            if in_browser_py and fn == "turns_sandbox_off":
                continue
            for switch in SWITCH.findall(node.value):
                if browser.turns_sandbox_off(switch):
                    out.append((node.lineno, "switch %s" % switch))
    return sorted(out)


# A launch named in a string where nothing is started, each read by hand.
NAMED = {
    # The names of calls that drive a browser, which send the core's test
    # files that make them to the core-browsers suite.
    ("tools/pytest_plugins/core_part.py", "Playwright launch by name"),
    ("tools/pytest_plugins/core_part.py", "Playwright launch_persistent_context by name"),
}

# A browser started with less than its whole sandbox on purpose, by (file,
# what the census finds), with why, each read by hand. None runs where a
# provider's page is opened.
ON_PURPOSE = {
    ("server/smoke.py", "switch --disable-namespace-sandbox"):
        "the image check's own Chrome, run inside the built container as pp with "
        "namespaces turned off so the setuid helper is its only first layer, as on a "
        "kernel without user namespaces. It proves that layer and seccomp-bpf still "
        "hold, reads only its own blank page, and never runs in an install",
}


SOURCES = sources()


def test_the_census_reads_every_app_and_the_core():
    names = {p.relative_to(REPO).as_posix() for p in SOURCES}
    apps = sorted(d.name for d in (REPO / "apps").iterdir() if (d / ("%s_site.py" % d.name)).exists())
    assert len(apps) >= 70
    for app in apps:
        assert "apps/%s/%s_site.py" % (app, app) in names, app
    assert {BROWSER_PY, "core/paperpull_core/receipt_pdf.py", "apps/target/target_receipts.py",
            "gui/app.py", "server/selftest.py", "paperpull.py"} <= names
    assert not [n for n in names if "/tests/" in n or n.split("/")[-1].startswith("test_")]


def _found(path):
    rel = path.relative_to(REPO).as_posix()
    found = unsandboxed(path.read_text(encoding="utf-8-sig"), rel)
    return [f for f in found if (rel, f[1]) not in NAMED and (rel, f[1]) not in ON_PURPOSE]


def test_every_launch_named_where_nothing_starts_is_still_there():
    """So the list above cannot hide a name that has moved."""
    for rel, what in NAMED:
        assert what in [w for _l, w in unsandboxed((REPO / rel).read_text(encoding="utf-8-sig"),
                                                   rel)], (rel, what)


def test_every_start_with_less_than_its_sandbox_on_purpose_is_still_there():
    """So the list of starts made on purpose cannot hide one that moved, and
    each says why."""
    for (rel, what), why in ON_PURPOSE.items():
        assert what in [w for _l, w in unsandboxed((REPO / rel).read_text(encoding="utf-8-sig"),
                                                   rel)], (rel, what)
        assert len(why.split()) >= 12, (rel, what)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.relative_to(REPO).as_posix())
def test_no_browser_starts_outside_its_sandbox(path):
    found = _found(path)
    assert not found, "%s could start a browser without its sandbox at %s. Start it " \
        "through browser.sandboxed_launch or sandboxed_persistent_context instead." % (
            path.relative_to(REPO).as_posix(), found)


def test_the_wrappers_are_the_only_launches_and_both_are_read():
    """browser.py itself is read, and its two launches are the ones let be."""
    src = (REPO / BROWSER_PY).read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    owner = _enclosing_functions(tree)
    launches = sorted((owner[id(n)], n.attr) for n in ast.walk(tree)
                      if isinstance(n, ast.Attribute) and n.attr in LAUNCHES)
    assert launches == [("sandboxed_launch", "launch"),
                        ("sandboxed_persistent_context", "launch_persistent_context")]


def test_the_census_finds_every_kind_it_is_for():
    """The census, on a source made for it. If one of these stops being
    found, the census above passes on nothing."""
    made = '''
def start(p, chromium, opts, name):
    p.chromium.launch(headless=True)
    chromium.launch_persistent_context("/x", headless=False)
    starter = chromium.launch
    getattr(chromium, "launch_persistent_context")("/x")
    getattr(chromium, name)
    chromium.launch_server()
    p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    browser.sandboxed_launch(chromium, chromium_sandbox=False)
    browser.sandboxed_launch(chromium, **{"chromium_sandbox": False})
    browser.sandboxed_launch(chromium, args=["--no-sandbox"])
    subprocess.Popen([exe, "--disable-setuid-sandbox", "--remote-debugging-port=9"])
    cmd = "chrome.exe -no-sandbox --user-data-dir=x"
    flags = ["--disable-features=NetworkServiceSandbox", "--single-process"]
'''
    found = [what for _line, what in unsandboxed(made)]
    assert found == [
        "Playwright launch", "Playwright launch_persistent_context", "Playwright launch",
        "Playwright launch_persistent_context by name", "Playwright launch_server", "chromium_sandbox given", "chromium_sandbox by name",
        "switch --no-sandbox", "switch --disable-setuid-sandbox", "switch -no-sandbox",
        "switch --disable-features=NetworkServiceSandbox", "switch --single-process"]


def test_the_census_lets_the_wrappers_be_in_browser_py_only():
    made = '''
def sandboxed_launch(chromium, **kwargs):
    return _started(chromium.launch, **_sandboxed(kwargs))

def _sandboxed(kwargs):
    if "chromium_sandbox" in kwargs:
        pass
    return dict(kwargs, chromium_sandbox=True)

def elsewhere(kw):
    kw["chromium_sandbox"] = False

def turns_sandbox_off(arg):
    """--no-sandbox and the like."""
'''
    assert [w for _l, w in unsandboxed(made, BROWSER_PY)] == ["chromium_sandbox by name"]
    assert [w for _l, w in unsandboxed(made, "core/paperpull_core/other.py")] == [
        "Playwright launch", "chromium_sandbox by name", "chromium_sandbox given",
        "chromium_sandbox by name", "switch --no-sandbox"]


# -- the wrappers ------------------------------------------------------------

class Chromium:
    """A stand-in browser type that notes what it was asked."""

    def __init__(self, fails=None):
        self.asked = []
        self.fails = fails

    def launch(self, **kwargs):
        self.asked.append(("launch", None, kwargs))
        if self.fails:
            raise self.fails
        return "browser"

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.asked.append(("persistent", user_data_dir, kwargs))
        if self.fails:
            raise self.fails
        return "context"


def test_both_wrappers_always_ask_for_the_sandbox():
    c = Chromium()
    assert browser.sandboxed_launch(c, headless=True) == "browser"
    assert browser.sandboxed_persistent_context(c, "/x/profile", headless=False,
                                                args=["--lang=en-US"]) == "context"
    assert browser.sandboxed_launch(c, chromium_sandbox=True) == "browser"
    assert c.asked == [
        ("launch", None, {"headless": True, "chromium_sandbox": True}),
        ("persistent", "/x/profile", {"headless": False, "args": ["--lang=en-US"],
                                      "chromium_sandbox": True}),
        ("launch", None, {"chromium_sandbox": True})]


@pytest.mark.parametrize("kwargs", [
    {"chromium_sandbox": False}, {"chromium_sandbox": None}, {"chromium_sandbox": 0},
    {"chromium_sandbox": "true"}, {"args": ["--no-sandbox"]}, {"args": ["--NO-SANDBOX"]},
    {"args": ["-no-sandbox"]}, {"args": "--no-sandbox"}, {"args": ("--disable-setuid-sandbox",)},
    {"args": ["--disable-features=NetworkServiceSandbox"]}, {"args": ["--disable-gpu-sandbox"]},
    {"args": ["--lang=en-US", "--single-process"]}, {"args": ["--no-zygote"]},
], ids=repr)
def test_a_caller_cannot_ask_for_less_than_the_sandbox(kwargs):
    for start in (lambda c: browser.sandboxed_launch(c, **kwargs),
                  lambda c: browser.sandboxed_persistent_context(c, "/x", **kwargs),
                  lambda c: browser.launch_own_browser(c, "/x", **kwargs)):
        c = Chromium()
        with pytest.raises(ValueError, match="without its sandbox"):
            start(c)
        assert c.asked == [], "a browser was asked for anyway"


def test_ordinary_switches_still_go_through():
    """A switch's value is read only for a feature switch, so a host named
    for a sandbox in the renderer's list of hosts is not taken for one."""
    for switch in ("--lang=en-US", "--window-size=1400,950", "--disable-extensions",
                   "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                   "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE sandbox.example.com"):
        assert not browser.turns_sandbox_off(switch), switch
        c = Chromium()
        browser.sandboxed_launch(c, args=[switch])
        assert c.asked[0][2]["args"] == [switch]


@pytest.mark.parametrize("switch", [
    "--in-process-gpu", "--renderer-cmd-prefix=gdb", "--browser-subprocess-path=/x",
    "--disable-site-isolation-trials", "--disable-features=RendererAppContainer",
    "--enable-features=WinSboxDisableExtensionPoints", "--user-data-dir=/x", "about:blank",
])
def test_a_switch_not_known_to_keep_the_sandbox_whole_is_refused(switch):
    """Many switches weaken the browser's isolation without naming a
    sandbox, so only switches read and named in browser.SAFE_SWITCHES go
    through."""
    for start in (lambda c: browser.sandboxed_launch(c, args=[switch]),
                  lambda c: browser.sandboxed_persistent_context(c, "/x", args=[switch])):
        c = Chromium()
        with pytest.raises(ValueError, match="not a switch known"):
            start(c)
        assert c.asked == []


# Playwright 1.63's words when Chromium could not start its sandbox, and
# Chromium's own as an older driver passed them through.
PLAYWRIGHT_SANDBOX_FAILED = (
    "BrowserType.launch: Target page, context or browser has been closed\nBrowser logs:\n\n"
    "Chromium sandboxing failed!\n================================\n"
    "To avoid the sandboxing issue, do either of the following:\n"
    "  - (preferred): Configure your environment to support sandboxing\n"
    "  - (alternative): Launch Chromium without sandbox using 'chromiumSandbox: false' option\n")
CHROMIUM_SAID = [
    "[FATAL:zygote_host_impl_linux.cc(128)] No usable sandbox! If you are running on Ubuntu 23.10+",
    "[FATAL:zygote_host_impl_linux.cc(127)] Running as root without --no-sandbox is not "
    "supported. See https://crbug.com/638180.",
    # Chrome 155 in a container under Docker's default seccomp profile, as
    # a plain user, passed through by Playwright 1.63 as it is.
    "BrowserType.launch: Target page, context or browser has been closed\nBrowser logs:\n"
    "[pid=19][err] [19:19:1016/105457.592210:FATAL:sandbox/linux/suid/client/"
    "setuid_sandbox_host.cc:172] The SUID sandbox helper binary was found, but is not "
    "configured correctly. Rather than run without sandboxing I'm aborting now. You need to "
    "make sure that /x/chrome-sandbox is owned by root and has mode 4755.",
]


@pytest.mark.parametrize("said", [PLAYWRIGHT_SANDBOX_FAILED] + CHROMIUM_SAID)
def test_a_sandbox_that_cannot_start_stops_the_launch_in_plain_words(said):
    for start in (lambda c: browser.sandboxed_launch(c, headless=True),
                  lambda c: browser.sandboxed_persistent_context(c, "/x", headless=True)):
        c = Chromium(fails=Exception(said))
        with pytest.raises(browser.SandboxRefused) as e:
            start(c)
        assert str(e.value) == browser.SANDBOX_REFUSED
        assert "chromiumSandbox" not in str(e.value) and "false" not in str(e.value).lower()
        assert e.value.__cause__ is None and e.value.__suppress_context__
        # Asked once, with the sandbox, and never again without it.
        assert [a[2]["chromium_sandbox"] for a in c.asked] == [True]


def test_an_own_browser_whose_sandbox_cannot_start_ends_the_run_and_says_why(capsys):
    c = Chromium(fails=Exception(PLAYWRIGHT_SANDBOX_FAILED))
    with pytest.raises(SystemExit) as e:
        browser.launch_own_browser(c, "/x/browser-profile", headless=False)
    assert str(e.value.code) == browser.SANDBOX_REFUSED
    assert [a[2]["chromium_sandbox"] for a in c.asked] == [True]


def test_another_launch_failure_is_passed_on_as_it_was():
    c = Chromium(fails=RuntimeError("Executable doesn't exist at /x/chrome"))
    with pytest.raises(RuntimeError, match="Executable doesn't exist"):
        browser.sandboxed_launch(c, headless=True)


# -- the sign-in browser, started by subprocess ---------------------------------

def test_the_sign_in_browser_is_started_with_nothing_that_turns_its_sandbox_off(
        monkeypatch, tmp_path):
    """The sign-in starts the person's browser by subprocess, never through
    Playwright, so no driver adds anything to its command line. What it is
    started with is read as it is handed to the system."""
    started = []

    def popen(argv, **kwargs):
        started.append(list(argv))
        raise OSError("not started in a test")

    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    for name in (browser.CHROMIUM, browser.EDGE, browser.CHROME):
        assert browser._launch("/x/chrome", name, tmp_path / name, "9333",
                               "https://example.invalid/", explain_failure=False) is None
    assert len(started) == 3
    for argv in started:
        assert any(a.startswith("--remote-debugging-port=") for a in argv), argv
        off = [a for a in argv if browser.turns_sandbox_off(a)]
        assert not off, "the sign-in browser would start with %s" % off


# -- real browsers, read from their own processes --------------------------------

def _command_lines(pw_browser) -> dict:
    """{process id: (kind, command line)} for every process of a running
    browser, the ids from the browser itself and the command lines from
    the system's process list."""
    session = pw_browser.new_browser_cdp_session()
    try:
        info = session.send("SystemInfo.getProcessInfo")["processInfo"]
    finally:
        session.detach()
    kinds = {int(p["id"]): p["type"] for p in info}
    lines = {}
    if sys.platform == "win32":
        ids = " OR ".join("ProcessId=%d" % pid for pid in kinds)
        script = ("Get-CimInstance Win32_Process -Filter '%s' | "
                  "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress" % ids)
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=120).stdout
        rows = json.loads(out or "[]")
        for row in [rows] if isinstance(rows, dict) else rows:
            if row.get("CommandLine"):
                lines[int(row["ProcessId"])] = row["CommandLine"]
    else:
        for pid in kinds:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=30).stdout
            if out.strip():
                lines[pid] = out.strip()
    # A helper process can end between the two questions, and is not
    # counted. _read still requires the browser's own and a renderer.
    return {pid: (kinds[pid], lines[pid]) for pid in kinds if pid in lines}


def _sandbox_off_in(processes: dict) -> list:
    """What in a browser's processes says its sandbox is off. The browser
    process may carry no switch that turns a sandbox off, and no process
    may carry --no-sandbox, which Chromium hands every child it starts."""
    found = []
    for pid, (kind, line) in processes.items():
        switches = SWITCH.findall(line)
        if kind == "browser":
            found += ["%s %s" % (kind, s) for s in switches if browser.turns_sandbox_off(s)]
        elif "--no-sandbox" in [s.lower() for s in switches]:
            found.append("%s --no-sandbox" % kind)
    return found


def _read(processes: dict) -> None:
    """Proof the process list was read, so an empty answer cannot pass.
    The browser's own process and a page's renderer were both read, each
    with a command line."""
    assert all(line for _kind, line in processes.values()), \
        "a process's command line was not read: %s" % processes
    kinds = {kind for kind, _line in processes.values()}
    assert {"browser", "renderer"} <= kinds, kinds
    browsers = [line for kind, line in processes.values() if kind == "browser"]
    assert all("--remote-debugging-pipe" in line for line in browsers), browsers


def _with_a_page(context):
    """A page open, so the browser has started a renderer to be read."""
    page = context.new_page()
    page.set_content("<p>a page</p>")
    return page


@pytest.fixture(scope="module")
def pw():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            p.chromium.executable_path
        except Exception:
            pytest.skip("no Playwright Chromium here")
        yield p


def test_reading_the_processes_sees_a_browser_started_without_its_sandbox(pw):
    """The reader below, shown seeing what it is for. Playwright's own
    launch, as every app made it before, carries --no-sandbox."""
    b = pw.chromium.launch(headless=True)
    try:
        _with_a_page(b.new_context())
        processes = _command_lines(b)
    finally:
        b.close()
    _read(processes)
    assert "browser --no-sandbox" in _sandbox_off_in(processes)
    assert "renderer --no-sandbox" in _sandbox_off_in(processes)


def test_a_headless_browser_starts_in_its_sandbox(pw):
    b = browser.sandboxed_launch(pw.chromium, headless=True)
    try:
        _with_a_page(b.new_context())
        processes = _command_lines(b)
    finally:
        b.close()
    _read(processes)
    assert _sandbox_off_in(processes) == []


def test_an_apps_own_browser_starts_in_its_sandbox(pw, tmp_path, capsys):
    """The browser of a run whose config names no cdp_url, as every app
    opens it, headless here only so no window opens during the tests."""
    # Named for this run alone, and found by that name, since a runner's
    # temporary folder can reach Chromium under another spelling of its path.
    profile = tmp_path / ("browser-profile-%d" % os.getpid())
    ctx = browser.launch_own_browser(pw.chromium, str(profile), headless=True,
                                     accept_downloads=True,
                                     viewport={"width": 1400, "height": 950})
    try:
        _with_a_page(ctx)
        processes = _command_lines(ctx.browser)
    finally:
        ctx.close()
    _read(processes)
    assert any(profile.name in line for kind, line in processes.values()
               if kind == "browser"), processes
    assert _sandbox_off_in(processes) == []


def test_the_receipt_renderers_browser_starts_in_its_sandbox(pw, tmp_path, monkeypatch):
    """The headless renderer starts its own browser. It is read the moment
    it has started, through the launch the renderer asks for."""
    from paperpull_core import receipt_pdf
    seen = []
    real = browser.sandboxed_launch

    def reading(chromium, **kwargs):
        b = real(chromium, **kwargs)
        ctx = b.new_context()
        _with_a_page(ctx)
        seen.append(_command_lines(b))
        ctx.close()
        return b

    monkeypatch.setattr(browser, "sandboxed_launch", reading)
    with pytest.raises(Exception, match="ERR_CONNECTION_REFUSED"):
        # An address nothing answers, so the page is never printed. The
        # browser was started all the same, and that is what is read.
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            address = "http://127.0.0.1:%d/" % s.getsockname()[1]
        receipt_pdf.render_url_headless(
            pw, {}, address, tmp_path / "out.pdf", wait_ms=0,
            is_safe_url=lambda u: str(u).startswith(address), hosts=("127.0.0.1",))
    assert len(seen) == 1
    _read(seen[0])
    assert _sandbox_off_in(seen[0]) == []
