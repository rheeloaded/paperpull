"""A sign-in that opened its window starts the run by itself once it is done.

The panel watches the window and starts the run, so the person never has to
come back to the panel. What is held here is the panel's half, its stream and
the page that listens to it: the wait that starts only for a sign-in that would
be followed by a run, the run it starts, and the ways out of it. What counts as
signed in is held in core/tests/test_signin_watch.py.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import run_result  # noqa: E402

GUI = Path(__file__).resolve().parents[1]
CORE = GUI.parent / "core"
APP = "Bank Statements"
PLAN = {"start": "https://bank.example/login", "markers": ["/login"], "inside": ["https://bank.example/docs"],
        "hosts": [], "dedicated": True, "start_is_inside": False}

STANDIN = '''
import sys
sys.path.insert(0, %(core)r)
from paperpull_core import browser
import types
site = types.ModuleType("bank_site")
site.URLS = {"login": "https://bank.example/login", "documents": "https://bank.example/docs"}
site.LOGIN_URL_MARKERS = ["/login"]
sys.modules["bank_site"] = site
browser._says_what_to_watch(lambda profile, port, url: "Chrome")("p", "9238", "https://bank.example/login")
print("Opened a sign-in browser.", flush=True)
'''


def _collect(stream):
    async def run():
        return "".join([chunk async for chunk in stream.body_iterator])
    return asyncio.run(run())


def _events(text):
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        name = lines[0][7:] if lines[0].startswith("event: ") else "message"
        out.append((name, lines[-1][6:]))
    return out


@pytest.fixture()
def install(tmp_path, monkeypatch):
    folder = tmp_path / APP
    folder.mkdir()
    (folder / "bank_docs.py").write_text(STANDIN % {"core": str(CORE)}, encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({"cdp_url": "http://127.0.0.1:9238"}), encoding="utf-8")
    meta = {"name": APP, "dir": str(folder), "script": "bank_docs.py", "script_name": "bank_docs.py",
            "template_dir": None, "python": sys.executable, "login_flag": "--open-browser",
            "accounts": ["primary"], "has_venv": True, "needs_setup": False, "runnable": True,
            "reviews_names": False}
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "discover_apps", lambda: {APP: meta})
    monkeypatch.setattr(app_module, "setup_needed", lambda meta: "")
    monkeypatch.setattr(app_module, "_account_config", lambda meta, account: folder / "config.json")
    monkeypatch.setattr(app_module, "SIGN_IN_LOOK_EVERY", 0)
    # No other config here names its port (test_a_port_another_config_names_is_not_watched).
    monkeypatch.setattr(app_module, "_port_is_only_its_own", lambda meta, account: True)
    app_module._RUNS.clear()
    app_module._SIGN_IN_PLANS.clear()
    yield folder
    app_module._RUNS.clear()
    app_module._SIGN_IN_PLANS.clear()


@pytest.fixture()
def tabs(monkeypatch):
    """The window's tabs, a list given in the order each look is to see them."""
    from paperpull_core import signin_watch
    answers = []
    monkeypatch.setattr(signin_watch, "read_tabs", lambda port: answers.pop(0) if len(answers) > 1 else answers[0])
    return answers


def _wait():
    """How the wait went, the "waiting" said at each look said once."""
    out = []
    for event in _events(_collect(app_module.api_sign_in_wait(APP, "primary"))):
        if not out or event != out[-1] or event != ("waiting", ""):
            out.append(event)
    return out


def _on(url, title="Your account"):
    return [{"url": url, "title": title}]


def test_a_run_that_opens_a_window_says_what_to_watch_to_the_panel_alone(install):
    stream = app_module._start_run(APP, "primary", "login", ())
    events = _events(_collect(stream))
    plans = [d for kind, d in events if "PAPERPULL_SIGN_IN_PLAN" in d]
    assert plans == [], "only the panel reads it, and the page never sees it"
    assert app_module._SIGN_IN_PLANS[(APP, "primary")]["start"] == "https://bank.example/login"
    assert ("done", "0") in events


def test_the_run_of_another_action_cannot_set_what_to_watch(install):
    stream = app_module._start_run(APP, "primary", "pilot", ())
    events = _events(_collect(stream))
    assert (APP, "primary") not in app_module._SIGN_IN_PLANS
    # Nor is the line it says shown among its own, with its mark.
    assert not [d for kind, d in events if "PAPERPULL_SIGN_IN_PLAN" in d], events
    assert ("message", "Opened a sign-in browser.") in events


def test_a_sign_in_starting_drops_what_an_earlier_one_said_to_watch(install):
    """A sign-in whose window says nothing to watch is waited for by nobody,
    never by what an earlier sign-in of the account said."""
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    (install / "bank_docs.py").write_text('print("Opened a sign-in browser.", flush=True)\n', encoding="utf-8")
    events = _events(_collect(app_module._start_run(APP, "primary", "login", ())))
    assert ("done", "0") in events
    assert (APP, "primary") not in app_module._SIGN_IN_PLANS


def test_a_marked_line_is_kept_and_an_unmarked_one_is_not():
    mark = run_result.new_mark()
    good = "PAPERPULL_SIGN_IN_PLAN %s %s" % (mark, json.dumps(PLAN))
    assert run_result.sign_in_plan(good, mark) == PLAN
    assert run_result.sign_in_plan("PAPERPULL_SIGN_IN_PLAN " + json.dumps(PLAN), mark) is None
    assert run_result.sign_in_plan(good, "ab" * 16) is None
    assert run_result.sign_in_plan("PAPERPULL_SIGN_IN_PLAN %s {}" % mark, mark) is None


def test_the_window_is_watched_until_the_sign_in_is_done(install, tabs):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.extend([_on("https://bank.example/login", "Sign in"), _on("https://bank.example/mfa", "Enter your code"),
                 _on("https://bank.example/accounts")])
    events = _wait()
    assert events[0][0] == "waiting" and events[-1] == ("ended", "signed_in")
    assert (APP, "primary") not in app_module._SIGN_IN_PLANS, "one wait for one press of the button"


def test_no_plan_means_nothing_can_be_told(install, tabs):
    assert _wait() == [("ended", "cannot_tell")]


def test_a_wait_gives_up_after_a_while(install, tabs, monkeypatch):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(_on("https://bank.example/login", "Sign in"))
    monkeypatch.setattr(app_module, "SIGN_IN_WAIT_SECONDS", 0)
    assert _wait() == [("waiting", ""), ("ended", "timed_out")]


def test_a_window_that_closes_ends_the_wait(install, tabs):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(None)
    assert _wait() == [("waiting", ""), ("ended", "no_window")]


def test_a_run_someone_pressed_ends_the_wait(install, tabs):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(_on("https://bank.example/login", "Sign in"))
    app_module._RUNS[(APP, "primary")] = {"action": "all", "started": ""}
    assert _wait() == [("waiting", ""), ("ended", "run_started")]


def test_the_sign_in_that_opened_the_wait_does_not_end_it(install, tabs):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(_on("https://bank.example/accounts"))
    app_module._RUNS[(APP, "primary")] = {"action": "login", "started": ""}
    assert _wait() == [("waiting", ""), ("ended", "signed_in")]


def test_not_on_paperpull_server(install, tabs, monkeypatch):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    monkeypatch.setenv("PAPERPULL_SERVER", "1")
    monkeypatch.setattr(app_module.server_mode, "enabled", lambda: True)
    assert _wait() == [("ended", "cannot_tell")]


def test_a_gone_account_is_refused(install):
    with pytest.raises(app_module.HTTPException) as e:
        app_module.api_sign_in_wait("Nobody", "primary")
    assert e.value.status_code == 404


def test_a_port_another_config_names_is_not_watched(install, tabs, monkeypatch):
    """Its window may be another account's sign-in, and this account's run
    would then save that account's documents as its own."""
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(_on("https://bank.example/accounts"))
    monkeypatch.setattr(app_module, "_port_is_only_its_own", lambda meta, account: False)
    assert _wait() == [("ended", "cannot_tell")]


def test_a_later_sign_in_of_the_account_ends_the_wait_for_the_earlier(install, monkeypatch):
    """Another tab's sign-in of the account is waited for there, and this
    page starts nothing for it, even when the window is signed in by then."""
    from paperpull_core import signin_watch
    key = (APP, "primary")
    app_module._SIGN_IN_PLANS[key] = dict(PLAN)
    looks = []

    def read(port):
        looks.append(port)
        if len(looks) == 2:
            app_module._SIGN_IN_PLANS[key] = dict(PLAN)
        return _on("https://bank.example/accounts")
    monkeypatch.setattr(signin_watch, "read_tabs", read)
    monkeypatch.setattr(signin_watch, "SETTLED_LOOKS", 2)
    assert _wait() == [("waiting", ""), ("ended", "replaced")]
    assert app_module._SIGN_IN_PLANS[key] == PLAN, "the later sign-in's own wait is still to come"
    # And one dropped as a sign-in starts, before it says what to watch.
    app_module._SIGN_IN_PLANS[key] = dict(PLAN)
    monkeypatch.setattr(app_module, "SIGN_IN_WAIT_SECONDS", 1)

    def starting(port):
        app_module._SIGN_IN_PLANS.pop(key, None)
        return _on("https://bank.example/login", "Sign in")
    monkeypatch.setattr(signin_watch, "read_tabs", starting)
    assert _wait() == [("waiting", ""), ("ended", "replaced")]


def test_of_two_waits_for_one_sign_in_one_is_told(install, tabs):
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.append(_on("https://bank.example/accounts"))

    async def both():
        async def one():
            stream = app_module.api_sign_in_wait(APP, "primary")
            return _events("".join([chunk async for chunk in stream.body_iterator]))[-1]
        return await asyncio.gather(one(), one())
    assert sorted(asyncio.run(both())) == [("ended", "replaced"), ("ended", "signed_in")]


def test_each_look_says_it_is_still_waiting(install, tabs):
    """So a page that went away, Stop waiting pressed or its tab closed,
    ends the wait at the next look rather than ten minutes later."""
    app_module._SIGN_IN_PLANS[(APP, "primary")] = dict(PLAN)
    tabs.extend([_on("https://bank.example/login", "Sign in")] * 4 + [None, None, None])
    events = _events(_collect(app_module.api_sign_in_wait(APP, "primary")))
    assert events.count(("waiting", "")) >= 6 and events[-1] == ("ended", "no_window")


# -- the page ---------------------------------------------------------------------

@pytest.fixture()
def panel():
    """The panel's own page with a stand-in for EventSource, as nothing here
    answers it, and startRun noted rather than sent."""
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--disable-extensions", "--no-first-run"])
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        tab = chromium.new_page()

        def answer(route):
            if route.request.url == "http://panel.test/":
                route.fulfill(status=200, content_type="text/html", body=html)
            else:
                route.abort()
        tab.route("**/*", answer)
        tab.goto("http://panel.test/")
        tab.evaluate("""() => {
            ROWS = [{app: 'Bank Statements', account: 'primary', provider: 'Bank', kind: 'DOCUMENT', state: 'current',
                     runnable: true, documents: 1, gaps: [], latest: [], runs: []}];
            // Nothing answers here, and a home page asks the server for more.
            loadAccounts = () => Promise.resolve();
            renderHome = () => {};
            window.opened = [];
            window.EventSource = class {
                constructor(url) { this.url = url; this.on = {}; this.closed = false; window.opened.push(this); }
                addEventListener(n, f) { this.on[n] = f; }
                close() { this.closed = true; }
                fire(n, data) { this.on[n]({data}); }
            };
            window.asked = [];
            const real = startRun;
            window.realStart = real;
            startRun = (r, action, opts) => { window.asked.push([action, opts]); return true; };
            window.loginDone = opts => {
                Object.assign(RUN, {state: 'running', action: 'login', app: 'Bank Statements', account: 'primary',
                                    provider: 'Bank', kind: 'DOCUMENT', who: '', scope: {year: '', start: '', end: ''},
                                    again: false, lines: [], result: null, saved: [], then: null, sink: null, startedAt: new Date(),
                                    onDone: null, queue: false}, opts || {});
                finishRun('0');
            };
        }""")
        yield tab
        chromium.close()


def test_a_sign_in_that_opened_starts_a_wait_and_then_get_new(panel):
    panel.evaluate("() => { VIEW = 'run'; loginDone(); }")
    assert panel.evaluate("() => SIGNIN_WAIT !== null")
    assert panel.evaluate("() => opened[0].url") == "/api/sign-in/wait?app=Bank+Statements&account=primary"
    assert panel.evaluate("() => RUN.outcome.say") == "Sign in to Bank in the window that opened and leave it open."
    assert panel.evaluate("() => document.title") == "Waiting for sign-in · PaperPull"
    shown = panel.evaluate("() => { renderRun(); return $('r-waiting').textContent; }")
    assert "Waiting for you to sign in" in shown and "Get new documents starts by itself" in shown
    assert panel.evaluate("() => $('r-waiting').querySelector('[data-do=\"stop-sign-in-wait\"]').textContent") == "Stop waiting"
    panel.evaluate("() => opened[0].fire('ended', 'signed_in')")
    asked = panel.evaluate("() => asked")
    assert asked == [["all", {"scope": {"year": "", "start": "", "end": ""}, "stay": False}]]
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => opened[0].closed")


def test_the_run_the_page_was_going_to_offer_is_the_one_that_starts(panel):
    panel.evaluate("""() => {
        VIEW = 'run';
        loginDone({then: {action: 'pilot', scope: {year: '2024', start: '', end: ''}, again: false}});
        opened[0].fire('ended', 'signed_in');
    }""")
    assert panel.evaluate("() => asked") == [["pilot", {"scope": {"year": "2024", "start": "", "end": ""}, "stay": False}]]


def test_on_another_page_it_starts_without_moving_the_person(panel):
    panel.evaluate("() => { VIEW = 'home'; loginDone(); opened[0].fire('ended', 'signed_in'); }")
    assert panel.evaluate("() => asked[0][1].stay") is True


@pytest.mark.parametrize("what, opts", [
    ("get help's sign-in", "{sink: document.createElement('pre')}"),
    ("a restore", "{then: {action: 'all', scope: {}, again: true}}"),
    ("a support report", "{then: {action: 'diagnose', scope: {}, again: false}}"),
    ("a recording", "{then: {action: 'record', scope: {}, again: false}}"),
    ("a run with no step of its own", "{then: {action: 'verify', scope: {}, again: false}}"),
])
def test_a_sign_in_with_no_run_to_start_does_not_wait(panel, what, opts):
    panel.evaluate("() => loginDone(%s)" % opts)
    assert panel.evaluate("() => SIGNIN_WAIT") is None, what
    assert panel.evaluate("() => opened.length") == 0


def test_a_sign_in_in_a_round_or_a_window_that_did_not_open_does_not_wait(panel):
    panel.evaluate("() => { QUEUE = {items: [], i: 0, held: true, finished: false}; loginDone(); QUEUE = null; }")
    assert panel.evaluate("() => SIGNIN_WAIT") is None
    panel.evaluate("""() => { Object.assign(RUN, {state: 'running', action: 'login', app: 'Bank Statements', account: 'primary',
        provider: 'Bank', kind: 'DOCUMENT', who: '', scope: {}, again: false, lines: [], result: null, saved: [], then: null,
        sink: null, startedAt: new Date(), onDone: null, queue: false}); finishRun('5'); }""")
    assert panel.evaluate("() => SIGNIN_WAIT") is None


@pytest.mark.parametrize("how, says", [("timed_out", "stopped waiting for your sign-in to Bank"),
                                       ("no_window", "was closed, so PaperPull stopped waiting")])
def test_a_wait_that_ends_on_its_own_says_so_and_starts_nothing(panel, how, says):
    panel.evaluate("() => { VIEW = 'run'; loginDone(); opened[0].fire('ended', '%s'); }" % how)
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => asked.length") == 0
    assert says in panel.evaluate("() => $('noticetext').textContent")


def test_a_watch_that_cannot_tell_is_a_sign_in_as_it_always_was(panel):
    panel.evaluate("() => { VIEW = 'run'; loginDone(); opened[0].fire('ended', 'cannot_tell'); renderRun(); }")
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => asked.length") == 0
    assert panel.evaluate("() => $('r-waiting')") is None
    # Nothing said of waiting, the page being as it always was.
    assert "waiting" not in panel.evaluate("() => $('noticetext').textContent")


def test_stop_waiting_stops_and_leaves_the_step(panel):
    during, said = panel.evaluate(
        "() => { VIEW = 'run'; loginDone(); const was = RUN.outcome.say; endSignInWait(); return [was, RUN.outcome.say]; }")
    assert during == "Sign in to Bank in the window that opened and leave it open."
    assert said == "Sign in to Bank in the window that opened and leave it open, then get new documents."
    panel.evaluate("() => { opened.length = 0; loginDone(); renderRun(); DO['stop-sign-in-wait'](); }")
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => opened[0].closed")
    assert panel.evaluate("() => asked.length") == 0 and panel.evaluate("() => $('r-waiting')") is None
    assert panel.evaluate("() => $('r-body').textContent.includes('Get new documents')")
    # The page says again what to press once signed in, which is the
    # person's to do now.
    assert panel.evaluate("() => RUN.outcome.say") == said


@pytest.mark.parametrize("how", ["replaced", "run_started"])
def test_a_wait_another_sign_in_or_run_took_over_starts_nothing(panel, how):
    panel.evaluate("() => { VIEW = 'run'; loginDone(); opened[0].fire('ended', '%s'); }" % how)
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => asked.length") == 0
    said = panel.evaluate("() => $('noticetext').textContent")
    assert "waiting" not in said and "sign-in" not in said, said


def test_pressing_a_run_by_hand_ends_the_wait_and_runs(panel):
    panel.evaluate("""() => {
        startRun = window.realStart;
        location.hash = '#/run'; VIEW = 'run';
        loginDone();
        renderRun();
    }""")
    panel.evaluate("""() => { document.querySelector('[data-do="run"][data-action="all"]').click(); }""")
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => opened[0].closed")
    assert panel.evaluate("() => RUN.action") == "all" and panel.evaluate("() => RUN.state") == "running"
    assert panel.evaluate("() => opened.length") == 2 and "/api/run?" in panel.evaluate("() => opened[1].url")


def test_a_wait_shows_in_the_bar_from_other_pages(panel):
    state = panel.evaluate("() => { VIEW = 'home'; loginDone(); renderRunbar(); return [$('runbar').hidden, $('rb-state').textContent]; }")
    assert state == [False, "Waiting for you to sign in"]
    assert panel.evaluate("() => { VIEW = 'run'; renderRunbar(); return $('runbar').hidden; }") is True


def test_the_page_never_starts_a_second_wait_after_a_wrong_sign_in(panel):
    """A wrong "signed in" runs once. The run finds nobody signed in and the
    page says so, and only a person pressing the button waits again."""
    panel.evaluate("() => { VIEW = 'run'; loginDone(); opened[0].fire('ended', 'signed_in'); }")
    panel.evaluate("""() => { startRun = window.realStart;
        Object.assign(RUN, {state: 'running', action: 'all', sink: null, onDone: null, queue: false, then: null});
        finishRun('7'); }""")
    assert panel.evaluate("() => opened.length") == 1 and panel.evaluate("() => SIGNIN_WAIT") is None


ROUND_AT = """([key, finished]) => {
    window.item = {key, provider: 'Bank', action: 'resume', scope: {year: '', start: '', end: ''}, said: 'held'};
    QUEUE = {items: [window.item], i: 0, held: !finished, finished, started: true};
    window.rounds = 0;
    queueRun = () => { window.rounds++; };
}"""


def test_a_sign_in_after_a_run_found_nobody_signed_in_starts_that_run(panel):
    panel.evaluate("""() => {
        VIEW = 'run';
        loginDone();
        endSignInWait();
        Object.assign(RUN, {state: 'running', action: 'all', result: null, then: null});
        finishRun('7');
        const then = signinThen(RUN);
        opened.length = 0;
        asked.length = 0;
        loginDone({then});
        opened[0].fire('ended', 'signed_in');
    }""")
    assert panel.evaluate("() => asked[0][0]") == "all"


def test_a_sign_in_at_the_account_a_round_stopped_at_carries_the_round_on(panel):
    panel.evaluate("() => { VIEW = 'run'; }")
    panel.evaluate(ROUND_AT, [panel.evaluate("() => keyOf(ROWS[0])"), False])
    panel.evaluate("() => loginDone()")
    assert panel.evaluate("() => SIGNIN_WAIT !== null")
    assert "Continue starts by itself" in panel.evaluate("() => { renderRun(); return $('r-waiting').textContent; }")
    panel.evaluate("() => opened[0].fire('ended', 'signed_in')")
    assert panel.evaluate("() => rounds") == 1, "the round tries the account again"
    assert panel.evaluate("() => asked") == [], "and starts no run of its own beside the round"


def test_a_round_that_moved_on_is_not_started_again_by_a_late_sign_in(panel):
    panel.evaluate(ROUND_AT, [panel.evaluate("() => keyOf(ROWS[0])"), False])
    panel.evaluate("() => { loginDone(); QUEUE.i = 1; QUEUE.items.push({key: 'x'}); opened[0].fire('ended', 'signed_in'); }")
    assert panel.evaluate("() => rounds") == 0 and panel.evaluate("() => asked") == []


def test_a_round_stopped_at_another_account_does_not_wait(panel):
    panel.evaluate(ROUND_AT, ["another", False])
    panel.evaluate("() => loginDone()")
    assert panel.evaluate("() => SIGNIN_WAIT") is None


def test_a_round_that_is_over_does_not_stop_a_later_sign_in_from_waiting(panel):
    panel.evaluate(ROUND_AT, [panel.evaluate("() => keyOf(ROWS[0])"), True])
    panel.evaluate("() => { loginDone(); opened[0].fire('ended', 'signed_in'); }")
    assert panel.evaluate("() => rounds") == 0
    assert panel.evaluate("() => asked[0][0]") == "all"
