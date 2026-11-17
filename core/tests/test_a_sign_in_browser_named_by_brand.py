"""A sign-in browser chosen by its brand (#222).

The "browser" setting took auto, installed or bundled, and anything else was
auto, so a person whose computer has Edge could not have PaperPull sign in
with Chrome. It also takes a brand now, edge, chrome, brave, vivaldi or
opera, in any case. Named, the sign-in browser is that brand as installed
here and nothing else, on a profile folder of its own beside the usual one,
with the ending a fallback to that brand already had. A brand that is not
installed, a browser of another brand on the port, and a value that is none
of these are each said, and nothing is launched.

No real browser starts here. subprocess.Popen, the port wait and the lists
of browsers on this computer are stand-ins, and a browser already on the
port is a small HTTP server on a port of its own.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from paperpull_core import browser

# The real ones, before the autouse fixture in conftest.py stands them in.
REAL_PORT_HOLDER = browser.debug_port_holder
REAL_OPEN_TAB_IN = browser._open_tab_in
REAL_BRING_FORWARD = browser.bring_forward

URL = "https://bank.example/sign-in"
PORT = "9231"

# What each brand's word is, and the ending its profile folder gets, which
# is the one _try_each already gave a fallback to that brand.
BRAND_TABLE = {
    "edge": (browser.EDGE, "-microsoftedge"),
    "chrome": (browser.CHROME, "-googlechrome"),
    "brave": (browser.BRAVE, "-brave"),
    "vivaldi": (browser.VIVALDI, "-vivaldi"),
    "opera": (browser.OPERA, "-opera"),
}
EIGHT = ("auto", "installed", "bundled", "edge", "chrome", "brave", "vivaldi", "opera")

EVERY_BRAND = [
    (browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome"), (browser.BRAVE, "/x/brave"),
    (browser.VIVALDI, "/x/vivaldi"), (browser.OPERA, "/x/opera"),
]


def _never(what):
    def refused(*_a, **_k):
        raise AssertionError(what)
    return refused


class _Running:
    """What Popen hands back for a browser that is still running."""

    def __init__(self, log, cmd):
        self.log, self.cmd = log, cmd

    def poll(self):
        return None

    def terminate(self):
        self.log.append(self.cmd[0])


def machine(monkeypatch, real, bundled=(), answers=True):
    """A computer with these browsers of the person's own and these bundled
    builds, where each launch's port answers or not. Answers what was
    launched, each command line in full."""
    monkeypatch.setattr(browser, "_real_browsers", lambda: list(real))
    monkeypatch.setattr(browser, "_bundled_chromium", lambda root=None: list(bundled))
    monkeypatch.setattr(browser, "fetch_bundled_chromium", _never("a download was offered"))
    monkeypatch.setattr(browser, "chromium_update_due", lambda path: None)
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    launched, ended = [], []

    def popen(cmd, **_k):
        launched.append(list(cmd))
        return _Running(ended, cmd)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, alive=None: answers)
    return launched


def folder_of(cmd) -> Path:
    arg = [a for a in cmd if a.startswith("--user-data-dir=")]
    assert len(arg) == 1, cmd
    return Path(arg[0].split("=", 1)[1])


# -- 1, 2, 3 only the named brand, and nothing in its place -------------------

def test_a_named_brand_is_the_only_candidate(monkeypatch):
    machine(monkeypatch, [(browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome")],
            bundled=["/pw/chromium-1200/chrome"])
    assert browser.browser_candidates(mode="chrome") == [(browser.CHROME, "/x/chrome")]


def test_a_named_brand_opens_that_brand_alone(monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome")],
                       bundled=["/pw/chromium-1200/chrome"])
    got = browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="chrome")
    assert got == browser.CHROME
    assert [cmd[0] for cmd in launched] == ["/x/chrome"]


def test_a_brand_not_installed_launches_nothing_and_says_so(monkeypatch, tmp_path, capsys):
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge")],
                       bundled=["/pw/chromium-1200/chrome"])
    monkeypatch.setattr(browser.subprocess, "Popen", _never("a browser was launched"))
    got = browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="chrome")
    out = capsys.readouterr().out
    assert got is None and launched == []
    assert "Google Chrome" in out and '"browser"' in out


def test_a_brand_not_installed_on_a_bare_computer_offers_no_download(monkeypatch, tmp_path, capsys):
    machine(monkeypatch, [])
    monkeypatch.setattr(browser.subprocess, "Popen", _never("a browser was launched"))
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="opera") is None
    assert "Opera" in capsys.readouterr().out


def test_a_named_brand_that_never_answers_offers_no_download(monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.CHROME, "/x/chrome")], answers=False)
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="chrome",
                                       allow_fetch=True) is None
    assert [cmd[0] for cmd in launched] == ["/x/chrome"]


def test_a_named_brand_is_never_offered_a_chromium_update_or_an_older_build(monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.CHROME, "/x/chrome")],
                       bundled=["/pw/chromium-1200/chrome", "/pw/chromium-1100/chrome"],
                       answers=False)
    monkeypatch.setattr(browser, "chromium_update_due", _never("an update was looked for"))
    monkeypatch.setattr(browser, "offer_chromium_update", _never("an update was offered"))
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="chrome")
    assert [cmd[0] for cmd in launched] == ["/x/chrome"]


# -- 4, 5 one spelling, and a value that is none of the eight ---------------

@pytest.mark.parametrize("value", ["chrome", "CHROME", "Chrome", "cHrOmE", " chrome", "chrome ",
                                   "\tChrome\n"])
def test_any_case_with_space_around_is_the_brand(value, monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome")],
                       bundled=["/pw/chromium-1200/chrome"])
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=value) == browser.CHROME
    assert [cmd[0] for cmd in launched] == ["/x/chrome"]
    assert folder_of(launched[0]).name == "p-googlechrome"


REFUSED_VALUES = ["google chrome", "msedge", "chromium", "firefox", "safari", "../chrome",
                  "chrome/../../x", "chrome\\..\\x", "chrome\u0000", "ｃｈｒｏｍｅ",
                  "chrome​", "chrome-x", "chrome edge", "-googlechrome", "--no-sandbox",
                  None, 7, 0, True, False, 1.5, ["chrome"], {}, {"chrome": 1}]


@pytest.mark.parametrize("value", REFUSED_VALUES, ids=repr)
def test_a_value_that_is_none_of_the_eight_is_refused_with_the_list(value, monkeypatch, tmp_path,
                                                                   capsys):
    machine(monkeypatch, EVERY_BRAND, bundled=["/pw/chromium-1200/chrome"])
    monkeypatch.setattr(browser.subprocess, "Popen", _never("a browser was launched"))
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=value) is None
    out = capsys.readouterr().out
    assert '"browser"' in out
    for word in EIGHT:
        assert word in out, word
    assert not (tmp_path / "p").exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("value", ["", "   ", "Auto", "AUTO", " auto "])
def test_empty_or_auto_in_any_case_is_auto(value, monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome")])
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=value) == browser.EDGE
    assert folder_of(launched[0]) == (tmp_path / "p").resolve()


def test_installed_in_any_case_is_installed(monkeypatch, tmp_path):
    """Before #222 "Installed" was auto, and the bundled copy went first."""
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge")],
                       bundled=["/pw/chromium-1200/chrome"])
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="Installed") == browser.EDGE
    assert [cmd[0] for cmd in launched] == ["/x/msedge"]


def test_bundled_in_any_case_is_bundled(monkeypatch, tmp_path):
    launched = machine(monkeypatch, [(browser.EDGE, "/x/msedge")],
                       bundled=["/pw/chromium-1200/chrome"])
    assert browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=" BUNDLED ") \
        == browser.CHROMIUM
    assert [cmd[0] for cmd in launched] == ["/pw/chromium-1200/chrome"]


# -- 6, 11, 12, 13 a browser already on the port ------------------------------

class _Holder(BaseHTTPRequestHandler):
    """A browser's debugging endpoint that says it is self.server.says."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/json/version":
            info = dict(self.server.says, webSocketDebuggerUrl="ws://127.0.0.1/devtools/browser/x")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(info).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        self.server.opened.append(self.path)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")


@pytest.fixture()
def holder(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Holder)
    srv.opened, srv.says = [], {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(browser, "debug_port_holder", REAL_PORT_HOLDER)
    monkeypatch.setattr(browser, "_open_tab_in", REAL_OPEN_TAB_IN)
    yield srv
    srv.shutdown()
    srv.server_close()


EDGE_SAYS = {"Browser": "Edg/141.0.3537.71",
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"}
CHROME_SAYS = {"Browser": "Chrome/141.0.7390.54",
               "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"}


def _nothing_launched_or_closed(monkeypatch):
    killed = []
    monkeypatch.setattr(browser.subprocess, "Popen", _never("a browser was launched"))
    monkeypatch.setattr(browser, "browser_candidates", _never("candidates were listed"))
    monkeypatch.setattr(browser.os, "kill", lambda pid, sig: killed.append(pid))
    return killed


def test_an_unknown_value_is_refused_before_the_port_is_asked(holder, monkeypatch, tmp_path,
                                                              capsys):
    holder.says = CHROME_SAYS
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    _nothing_launched_or_closed(monkeypatch)
    monkeypatch.setattr(browser, "_say_shared_port", _never("the shared port was said"))
    monkeypatch.setattr(browser, "_port_taken", _never("the port was looked at"))
    asked = []
    monkeypatch.setattr(browser, "debug_port_holder",
                        lambda p, timeout=1.5: asked.append(p) or REAL_PORT_HOLDER(p, timeout))
    assert browser.open_signin_browser(tmp_path / "p", port, URL, mode="firefox") is None
    assert asked == [] and holder.opened == []
    assert "A browser is already listening" not in capsys.readouterr().out


@pytest.mark.parametrize("word", ["chrome", "brave", "vivaldi", "opera"])
def test_edge_on_the_port_is_said_and_left_alone_for_another_brand(word, holder, monkeypatch,
                                                                   tmp_path, capsys):
    holder.says = EDGE_SAYS
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    killed = _nothing_launched_or_closed(monkeypatch)
    forward = []
    monkeypatch.setattr(browser, "bring_forward", lambda p: forward.append(p) or False)
    got = browser.open_signin_browser(tmp_path / "p", port, URL, mode=word)
    out = capsys.readouterr().out
    assert got is None
    assert holder.opened == [] and killed == [] and forward == []
    assert "Edge" in out and "close" in out.lower() and BRAND_TABLE[word][0] in out
    assert not (tmp_path / ("p" + BRAND_TABLE[word][1])).exists()


@pytest.mark.parametrize("says", [CHROME_SAYS, {"Browser": "HeadlessChrome/141.0.0.0"},
                                  {"Browser": "Chrome/141.0.0.0", "User-Agent": "Brave"},
                                  {}], ids=["chrome", "headless", "brave", "no name"])
def test_another_brand_on_the_port_is_said_and_left_alone_for_edge(says, holder, monkeypatch,
                                                                   tmp_path, capsys):
    """/json/version tells Edge from the rest, so with edge named anything
    that does not say Edg/ is another brand, a missing name included."""
    holder.says = says
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    killed = _nothing_launched_or_closed(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, URL, mode="edge") is None
    out = capsys.readouterr().out
    assert holder.opened == [] and killed == []
    assert "Microsoft Edge" in out and "close" in out.lower()


@pytest.mark.parametrize("word,says", [
    ("chrome", CHROME_SAYS), ("edge", EDGE_SAYS), ("brave", CHROME_SAYS),
    ("vivaldi", CHROME_SAYS), ("opera", CHROME_SAYS),
    ("chrome", {"Browser": "HeadlessChrome/141.0.0.0"}), ("chrome", {}),
    # Only Browser is read. Edge's User-Agent says Chrome/ too, and this one
    # says Edg/ with no Browser at all.
    ("chrome", {"User-Agent": EDGE_SAYS["User-Agent"]}),
], ids=["chrome", "edge", "brave", "vivaldi", "opera", "headless", "no name", "user agent only"])
def test_a_browser_that_may_be_the_brand_is_used_as_before(word, says, holder, monkeypatch,
                                                            tmp_path):
    """Chrome, Brave, Vivaldi, Opera and Chromium all say Chrome/, so only
    Edge against the rest can be told, and the rest is used as today."""
    holder.says = says
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    _nothing_launched_or_closed(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, URL, mode=word) \
        == browser.ALREADY_ON_PORT
    assert len(holder.opened) == 1


def test_the_user_agent_never_decides_for_edge(holder, monkeypatch, tmp_path):
    """No Browser name and an Edge User-Agent, with edge named, is not
    taken as Edge."""
    holder.says = {"User-Agent": EDGE_SAYS["User-Agent"]}
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    _nothing_launched_or_closed(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, URL, mode="edge") is None
    assert holder.opened == []


@pytest.mark.parametrize("mode", ["auto", "installed", "bundled"])
def test_without_a_brand_any_browser_on_the_port_is_used_as_before(mode, holder, monkeypatch,
                                                                   tmp_path):
    holder.says = EDGE_SAYS
    port = str(holder.server_address[1])
    machine(monkeypatch, EVERY_BRAND)
    _nothing_launched_or_closed(monkeypatch)
    assert browser.open_signin_browser(tmp_path / "p", port, URL, mode=mode) \
        == browser.ALREADY_ON_PORT
    assert len(holder.opened) == 1


# -- 7, 8, 10, 14, 15 the brand's own profile folder ------------------------

@pytest.mark.parametrize("word", sorted(BRAND_TABLE))
def test_each_brand_opens_on_a_folder_of_its_own_beside_the_usual_one(word, monkeypatch, tmp_path):
    launched = machine(monkeypatch, EVERY_BRAND, bundled=["/pw/chromium-1200/chrome"])
    profile = tmp_path / "Chase" / "chase-browser-profile"
    assert browser.open_signin_browser(profile, PORT, URL, mode=word) == BRAND_TABLE[word][0]
    got = folder_of(launched[0])
    assert got.is_absolute()
    assert got == browser.profile_folder(profile).with_name(
        "chase-browser-profile" + BRAND_TABLE[word][1])
    assert got != browser.profile_folder(profile)


@pytest.mark.parametrize("word", sorted(BRAND_TABLE))
def test_the_brand_folder_is_the_one_a_fallback_to_it_already_had(word, monkeypatch, tmp_path):
    """An auto setup whose first browser would not open fell back to this
    brand on this very folder, so a person who names it keeps that sign-in."""
    fell_back = machine(monkeypatch, [(browser.CHROMIUM, "/x/broken")] +
                        [c for c in EVERY_BRAND if c[0] == BRAND_TABLE[word][0]])
    answers = iter([False, True])
    monkeypatch.setattr(browser, "wait_for_debug_port",
                        lambda port, timeout=20.0, alive=None: next(answers))
    browser._try_each(browser._real_browsers(), tmp_path / "p", PORT, URL)
    launched = machine(monkeypatch, EVERY_BRAND)
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=word)
    assert folder_of(launched[0]) == folder_of(fell_back[1])


@pytest.mark.parametrize("parent", ["Zoë", "山田", "with space"])
def test_a_brand_folder_under_any_parent_is_in_that_parent(parent, monkeypatch, tmp_path):
    launched = machine(monkeypatch, EVERY_BRAND)
    profile = tmp_path / parent / "browser-profile"
    browser.open_signin_browser(profile, PORT, URL, mode="vivaldi")
    got = folder_of(launched[0])
    assert got.parent == browser.profile_folder(profile).parent
    assert got.name == "browser-profile-vivaldi"


def test_a_second_install_of_the_brand_gets_the_same_folder(monkeypatch, tmp_path):
    """On Linux /usr/bin/chromium is filed under Chrome. Tried after
    google-chrome, it opens on the same brand folder, never one with the
    ending twice, which nothing else would know as this account's."""
    launched = machine(monkeypatch, [(browser.CHROME, "/usr/bin/google-chrome"),
                                     (browser.CHROME, "/usr/bin/chromium")], answers=False)
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="chrome")
    for cmd in launched:
        assert folder_of(cmd).name == "p-googlechrome", cmd


def test_the_first_sign_in_with_a_brand_says_it_costs_one(monkeypatch, tmp_path, capsys):
    machine(monkeypatch, EVERY_BRAND)
    (tmp_path / "p").mkdir()
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="brave")
    first = capsys.readouterr().out
    assert "profile folder of its own" in first and "sign in" in first.lower()
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="brave")
    again = capsys.readouterr().out
    assert "profile folder of its own" not in again


@pytest.mark.parametrize("mode", ["auto", "installed", "bundled"])
def test_without_a_brand_nothing_is_said_of_a_new_folder(mode, monkeypatch, tmp_path, capsys):
    machine(monkeypatch, EVERY_BRAND, bundled=["/pw/chromium-1200/chrome"])
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=mode)
    assert "profile folder of its own" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["edge", "Chrome", " BRAVE ", "vivaldi", "OPERA"])
def test_the_command_line_is_exactly_as_before_with_the_brand_folder(value, monkeypatch, tmp_path):
    launched = machine(monkeypatch, EVERY_BRAND)
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode=value)
    word = value.strip().lower()
    exe = dict(EVERY_BRAND)[BRAND_TABLE[word][0]]
    folder = browser.profile_folder(tmp_path / "p").with_name("p" + BRAND_TABLE[word][1])
    assert launched == [[exe, "--user-data-dir=%s" % folder, "--remote-debugging-port=%s" % PORT,
                         "--no-first-run", "--no-default-browser-check", "--", URL]]
    assert not any(value in arg for arg in launched[0] if value != word)


def _launch_tests():
    """test_browser_launch.py's own REFUSED and TAKEN, read from it, so the
    two lists stay one."""
    import importlib.util
    path = Path(__file__).with_name("test_browser_launch.py")
    spec = importlib.util.spec_from_file_location("_launch_cases_222", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Space around an address is taken off before it is read, so one that is a
# web address once taken off is not refused here.
REFUSED_ADDRESSES = [url for url in _launch_tests().REFUSED
                     if not (isinstance(url, str) and browser.signin_address_ok(url.strip()))]
TAKEN_ADDRESSES = _launch_tests().TAKEN


@pytest.mark.parametrize("url", REFUSED_ADDRESSES, ids=repr)
def test_with_a_brand_an_address_that_is_not_a_web_address_opens_nothing(url, monkeypatch,
                                                                         tmp_path):
    machine(monkeypatch, EVERY_BRAND)
    monkeypatch.setattr(browser.subprocess, "Popen", _never("a browser was launched"))
    assert browser.open_signin_browser(tmp_path / "p", PORT, url, mode="chrome") is None


@pytest.mark.parametrize("url", TAKEN_ADDRESSES)
def test_with_a_brand_the_address_goes_after_the_end_of_the_switches(url, monkeypatch, tmp_path):
    launched = machine(monkeypatch, EVERY_BRAND)
    browser.open_signin_browser(tmp_path / "p", PORT, url, mode="chrome")
    args = launched[0]
    assert args[-2:] == ["--", url.strip()]
    assert args.count("--") == 1
    assert all(a.startswith("--") for a in args[1:-2])


# -- preserved, auto, installed and bundled ---------------------------------

@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize("prefer_real", [False, True])
def test_the_three_old_values_keep_their_order_and_folder(platform, prefer_real, monkeypatch,
                                                         tmp_path):
    monkeypatch.setattr(browser.sys, "platform", platform)
    real = [(browser.EDGE, "/x/msedge"), (browser.CHROME, "/x/chrome")]
    bundled = ["/pw/chromium-1200/chrome-linux/chrome"]
    machine(monkeypatch, real, bundled=bundled)
    chromium = [(browser.CHROMIUM, bundled[0])]
    assert browser.browser_candidates(prefer_real, "bundled") == chromium
    assert browser.browser_candidates(prefer_real, "installed") == real
    assert browser.browser_candidates(prefer_real, "auto") == \
        (real + chromium if prefer_real else chromium + real)
    launched = machine(monkeypatch, real, bundled=bundled)
    browser.open_signin_browser(tmp_path / "p", PORT, URL, prefer_real=prefer_real, mode="auto")
    assert folder_of(launched[0]) == browser.profile_folder(tmp_path / "p")


def test_auto_falls_back_on_the_endings_it_always_used(monkeypatch, tmp_path):
    launched = machine(monkeypatch, EVERY_BRAND, answers=False)
    browser.open_signin_browser(tmp_path / "p", PORT, URL, mode="installed")
    names = [folder_of(cmd).name for cmd in launched]
    assert names == ["p", "p-googlechrome", "p-brave", "p-vivaldi", "p-opera"]


# -- 9 closed after a run ---------------------------------------------------

class _Out:
    def __init__(self, stdout):
        self.stdout = stdout


def _mac(monkeypatch, lines):
    monkeypatch.setattr(browser.sys, "platform", "darwin")

    def run(cmd, **k):
        if cmd[0] == "ps":
            return _Out("\n".join(lines))
        if cmd[:2] == ["lsappinfo", "front"]:
            return _Out("ASN:0x0-0x1:")
        return _Out('"pid"=1')
    monkeypatch.setattr(browser.subprocess, "run", run)
    killed = []
    monkeypatch.setattr(browser.os, "kill", lambda pid, sig: killed.append(pid))
    return killed


FLAG = "--remote-" + "debugging-port="


@pytest.mark.parametrize("word", sorted(BRAND_TABLE))
def test_the_brand_window_is_closed_after_a_run_and_no_other(word, monkeypatch, tmp_path):
    mine = tmp_path / "Chase" / "browser-profile"
    real = browser.profile_folder(mine)
    brand = str(real) + BRAND_TABLE[word][1]
    spouse = str(real) + "-spouse" + BRAND_TABLE[word][1]
    killed = _mac(monkeypatch, [
        "300 /Apps/B --user-data-dir=%s %s9237 --no-first-run" % (brand, FLAG),
        "400 /Apps/B --user-data-dir=%s %s9236 --no-first-run" % (spouse, FLAG),
        "500 /Apps/B --user-data-dir=%s %s9236 --no-first-run" % (brand, FLAG),
    ])
    assert browser.close_signin_browser(mine, 9236) == {"closed": True, "in_use": False}
    assert killed == [500]


def test_a_brand_folder_on_another_port_is_left(monkeypatch, tmp_path):
    mine = tmp_path / "browser-profile"
    brand = str(browser.profile_folder(mine)) + "-googlechrome"
    killed = _mac(monkeypatch, ["500 /Apps/B --user-data-dir=%s %s9237 --x" % (brand, FLAG)])
    assert browser.close_signin_browser(mine, 9236)["closed"] is False and killed == []


# -- PaperPull Server -------------------------------------------------------

def _server(monkeypatch, tmp_path):
    machine(monkeypatch, [(browser.CHROME, "/usr/bin/google-chrome-stable")])
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    opened = []

    def launch(exe, name, profile_dir, port, url, explain_failure=True, mode=browser.AUTO):
        opened.append((exe, Path(profile_dir)))
        return name
    monkeypatch.setattr(browser, "_launch", launch)
    return opened


@pytest.mark.parametrize("mode", ["auto", "chrome", "Chrome"])
def test_on_the_server_auto_and_chrome_open_its_chrome_on_its_profile(mode, monkeypatch, tmp_path):
    """The image has one browser, Chrome, and auto has always opened it on
    the account's folder. Named, it is the same browser on the same folder,
    so an account named x-googlechrome never shares one with account x."""
    opened = _server(monkeypatch, tmp_path)
    profile = tmp_path / "profiles" / "Chase - x"
    assert browser.open_signin_browser(profile, PORT, URL, mode=mode) == browser.CHROME
    assert opened == [("/usr/bin/google-chrome-stable", profile)]


@pytest.mark.parametrize("word", ["edge", "brave", "vivaldi", "opera"])
def test_on_the_server_a_brand_it_does_not_have_is_refused(word, monkeypatch, tmp_path, capsys):
    opened = _server(monkeypatch, tmp_path)
    assert browser.open_signin_browser(tmp_path / "profiles" / "Chase", PORT, URL, mode=word) is None
    assert opened == [] and BRAND_TABLE[word][0] in capsys.readouterr().out
