"""A provider's first shell, in the panel.

A first shell opens the provider's site for a sign-in and downloads nothing
yet. Its site says so in NOT_MAPPED, and gui/providers.json says "shell":
true for it, which core/tests/test_signin_watch.py holds equal to NOT_MAPPED
for every app. The panel's own step after any sign-in was Get new, and a
shell's Get new stops and leaves its account "stopped", which offered
Continue and paused every round of Get new for all there. So the panel
reads the flag and, for a shell, names Record steps after its sign-in,
leaves it out of Get new for all and never counts it as a stopped account
to continue.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")

REPO = Path(__file__).resolve().parents[2]
CARDS = json.loads((REPO / "gui" / "providers.json").read_text(encoding="utf-8"))["providers"]
SHELL, BUILT = "Scalable Capital Statements", "Bank Statements"


# -- what the panel is told ---------------------------------------------------------

@pytest.fixture()
def root(tmp_path, monkeypatch):
    """An apps root with a shell's install and a built provider's install,
    each named for its entry script as a real install is."""
    apps = tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", str(apps))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    monkeypatch.setattr(app_module, "_STATUS_MOD", None)
    app_module._RUNS.clear()
    for folder, script, provider in ((SHELL, "scalable_docs.py", "Scalable Capital"),
                                     (BUILT, "chase_docs.py", "Bank")):
        d = apps / folder
        d.mkdir(parents=True)
        (d / script).write_text("print('stand-in')\n", encoding="utf-8")
        (d / "storage.py").write_text('SPEC = AppSpec(\n    provider="%s",\n    kind=DOCUMENT,\n)\n' % provider,
                                      encoding="utf-8")
        (d / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    yield apps
    app_module._RUNS.clear()


def _rows():
    return {r["app"]: r for r in app_module.account_rows()}


def test_the_cards_mark_the_two_shells_and_nothing_else():
    assert sorted(s for s, c in CARDS.items() if c.get("shell") is True) == ["consorsbank", "scalable"]


def test_each_row_says_whether_it_is_a_shell(root):
    rows = _rows()
    assert rows[SHELL]["shell"] is True and rows[BUILT]["shell"] is False
    # Said from the panel's own cards, never from a file in the person's folder.
    assert app_module._provider_notes()["scalable"]["shell"] is True
    assert app_module._provider_notes()["chase"]["shell"] is False


def test_a_shell_whose_last_run_stopped_is_still_told_as_one(root):
    """The row's state stays what its run log says, a stopped run, and the
    page is what keeps it from offering Continue."""
    (root / SHELL / app_module.RUN_LOG).write_text(json.dumps([
        {"action": "all", "exit_code": 0, "result": {"stopped": 1}}]), encoding="utf-8")
    row = _rows()[SHELL]
    assert row["state"] == "stopped" and row["shell"] is True


def test_a_row_that_cannot_be_read_still_says_whether_it_is_a_shell(root, monkeypatch):
    monkeypatch.setattr(app_module, "_account_row", lambda *a, **k: 1 / 0)
    rows = _rows()
    assert rows[SHELL]["shell"] is True and rows[BUILT]["shell"] is False


@pytest.mark.parametrize("content", ["", "{", '{"groups": {}}', '{"groups": {}, "providers": []}',
                                     '{"groups": {}, "providers": {"scalable": {"shell": "yes"}}}'])
def test_a_broken_card_file_calls_nothing_a_shell(content, tmp_path, monkeypatch):
    cards = tmp_path / "providers.json"
    cards.write_text(content, encoding="utf-8")
    monkeypatch.setattr(app_module, "PROVIDER_CARDS", cards)
    assert not any(n.get("shell") for n in app_module._provider_notes().values())


# -- the page -----------------------------------------------------------------------

ROW = {"kind": "DOCUMENT", "runnable": True, "needs_setup": False, "documents": 0, "gaps": [], "latest": [],
       "runs": [], "running": None, "settled": False, "last_run": None, "last_outcome": "", "owner": "",
       "group": "investing", "gets": "Statements"}


@pytest.fixture()
def panel():
    """The panel's own page in Playwright's Chromium with a shell's row and a
    built provider's row, nothing else answered, EventSource a stand-in and
    startRun noted rather than sent."""
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
        tab.evaluate("""([shell, built, base]) => {
            META = {apps: {[shell]: {}, [built]: {}}, apps_root: 'C:/PaperPull', documents_root: ''};
            window.row = (app, provider, state, more) => Object.assign({}, base, {app, provider, account: 'primary',
                state, shell: app === shell}, more || {});
            ROWS = [row(shell, 'Scalable Capital', 'not_started'), row(built, 'Bank', 'not_started')];
            loadAccounts = () => Promise.resolve();
            window.opened = [];
            window.EventSource = class {
                constructor(url) { this.url = url; this.on = {}; window.opened.push(this); }
                addEventListener(n, f) { this.on[n] = f; }
                close() {}
            };
            window.asked = [];
            window.realStart = startRun;
            startRun = (r, action, opts) => { window.asked.push([action, opts || {}]); return true; };
            // A run of an account that has just ended with this code.
            window.ended = (app, action, code, more) => {
                const r = rowFor(app, 'primary');
                Object.assign(RUN, {state: 'running', action, app, account: 'primary', provider: r.provider,
                                    kind: 'DOCUMENT', who: '', shell: Boolean(r.shell),
                                    scope: {year: '', start: '', end: ''}, again: false, lines: [], result: null,
                                    saved: [], then: null, sink: null, startedAt: new Date(), onDone: null,
                                    queue: false}, more || {});
                finishRun(code);
                VIEW = 'run';
                renderRun();
                return $('r-body');
            };
        }""", [SHELL, BUILT, ROW])
        yield tab
        chromium.close()


def _steps(panel):
    """Each next step the Run page offers, as [title, what its button does]."""
    return panel.evaluate("""() => [...document.querySelectorAll('#r-body ol.nextsteps li')].map(li => {
        const b = li.querySelector('button');
        return [li.querySelector('b').textContent, b.dataset.do + (b.dataset.action ? ':' + b.dataset.action : '')];
    })""")


def test_after_a_shells_sign_in_the_step_is_record_steps(panel):
    panel.evaluate("() => ended(%s, 'login', '0')" % json.dumps(SHELL))
    assert _steps(panel) == [["Record steps", "record"]]
    assert panel.evaluate("() => RUN.outcome.say") == (
        "Sign in to Scalable Capital in the window that opened and leave it open, then record steps.")
    # A recording opens its dialog, so nothing starts by itself.
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => opened.length") == 0
    assert panel.evaluate("() => asked") == []


def test_a_built_providers_sign_in_is_still_followed_by_get_new(panel):
    panel.evaluate("() => ended(%s, 'login', '0')" % json.dumps(BUILT))
    assert _steps(panel) == [["Get new documents", "run:all"]]
    assert panel.evaluate("() => SIGNIN_WAIT !== null")


@pytest.mark.parametrize("then", ["all", "pilot", "discover", "resume", "record"])
def test_a_shells_sign_in_after_any_run_but_a_report_is_followed_by_record_steps(panel, then):
    """A sign-in pressed on a finished run's page is followed by that run,
    which for a shell would only stop again."""
    panel.evaluate("""([app, then]) => ended(app, 'login', '0',
        {then: {action: then, scope: {year: '2024', start: '', end: ''}, again: false}})""", [SHELL, then])
    assert _steps(panel) == [["Record steps", "record"]]
    assert panel.evaluate("() => SIGNIN_WAIT") is None and panel.evaluate("() => opened.length") == 0


def test_a_shells_sign_in_after_a_restore_is_followed_by_record_steps(panel):
    panel.evaluate("""(app) => ended(app, 'login', '0',
        {then: {action: 'all', scope: {year: '2024', start: '', end: ''}, again: true}})""", SHELL)
    assert _steps(panel) == [["Record steps", "record"]]


def test_a_shells_support_report_stays_one_after_its_sign_in(panel):
    panel.evaluate("""(app) => ended(app, 'login', '0',
        {then: {action: 'diagnose', scope: {}, again: false}})""", SHELL)
    assert _steps(panel) == [["Make a support report", "support"]]


@pytest.mark.parametrize("action, result", [
    ("all", {"stopped": 1}), ("pilot", {"stopped": 1}), ("discover", {"stopped": 1}),
    ("resume", {"stopped": 1, "list_not_read": 1}), ("all", {"stopped": 1, "stop": "needs_you"}),
])
def test_a_shells_run_that_stopped_offers_record_steps_never_continue(panel, action, result):
    body = "() => ended(%s, %s, '0', {result: %s}).textContent" % (json.dumps(SHELL), json.dumps(action),
                                                                    json.dumps(result))
    shown = panel.evaluate(body)
    assert panel.evaluate("() => RUN.outcome.title") == "Scalable Capital is not built yet"
    assert "nothing was lost" in shown
    assert _steps(panel) == [["Record steps", "record"]]
    assert panel.evaluate("() => document.querySelector('#r-body [data-action=\"resume\"]')") is None


@pytest.mark.parametrize("action", ["all", "pilot", "resume", "discover"])
@pytest.mark.parametrize("code, result", [("stopped", None), ("lost", None), ("130", None), ("1", None),
                                          ("1", {"stopped": 1, "stop": "page"}),
                                          ("1", {"stopped": 1, "stop": "needs_you"})])
def test_no_ending_of_a_shells_run_offers_continue_or_check_again(panel, action, code, result):
    """Nothing on the panel starts a run that downloads for a shell now, and
    should one end some other way than its own stop, still nothing offers to
    carry it on."""
    panel.evaluate("([app, action, code, result]) => ended(app, action, code, {result})",
                   [SHELL, action, code, result])
    steps = _steps(panel)
    assert not [s for s in steps if s[1] in ("run:resume", "run:discover", "run:all", "run:pilot")], steps
    assert not panel.evaluate("() => RUN.outcome.resume || RUN.outcome.recheck")


def test_a_built_providers_run_that_stopped_still_offers_continue(panel):
    panel.evaluate("() => ended(%s, 'all', '0', {result: {stopped: 1}})" % json.dumps(BUILT))
    assert panel.evaluate("() => RUN.outcome.title") == "Stopped before finishing"
    assert ["Continue where it stopped", "run:resume"] in _steps(panel)


def test_a_shells_get_new_with_nobody_signed_in_offers_record_steps_after_the_sign_in(panel):
    panel.evaluate("() => ended(%s, 'all', '7')" % json.dumps(SHELL))
    assert _steps(panel) == [["Sign in to Scalable Capital", "run:login"], ["Record steps", "record"]]


@pytest.mark.parametrize("state, more", [
    ("stopped", {"last_outcome": "stopped", "last_run": {"action": "all", "result": {"stopped": 1}}}),
    ("stopped", {"last_outcome": "failed"}), ("due", {}), ("overdue", {}), ("never", {}),
    ("gap", {"gaps": [{"after": "2024-01-01", "before": "2024-03-01", "missing": 1}]}),
])
def test_a_shell_is_left_out_of_get_new_for_all_and_never_continued(panel, state, more):
    names = panel.evaluate("""([shell, built, state, more]) => {
        ROWS = [row(shell, 'Scalable Capital', state, more), row(built, 'Bank', state, more)];
        return [queueTargets().map(r => r.provider), continues(ROWS[0]), groupOf(ROWS[0]), present(ROWS[0])];
    }""", [SHELL, BUILT, state, more])
    targets, carried_on, group, said = names
    assert targets == ["Bank"], "only the built provider is in a round"
    assert carried_on is False and group == "new"
    assert said["chip"]["text"] == "Not built yet" and said["act"] == {"label": "Sign in", "run": "login",
                                                                      "primary": True}


def test_a_round_of_get_new_for_all_never_reaches_a_stopped_shell(panel):
    """The home page's summary counts only what a round would run, and a
    round started from it holds no shell."""
    shown = panel.evaluate("""([shell, built]) => {
        const stopped = {last_outcome: 'stopped', last_run: {action: 'all', result: {stopped: 1}}};
        ROWS = [row(shell, 'Scalable Capital', 'stopped', stopped), row(built, 'Bank', 'due'),
                row('Card Statements', 'Card', 'overdue')];
        META.apps['Card Statements'] = {};
        VIEW = 'home'; renderHome();
        startQueue();
        return [document.querySelector('#h-body .summary').textContent, QUEUE.items.map(it => it.provider),
                [...document.querySelectorAll('#h-body .h-sec')].map(s => [s.querySelector('h2, summary').textContent,
                  [...s.querySelectorAll('.acct .who a')].map(a => a.textContent)])];
    }""", [SHELL, BUILT])
    summary, round_, sections = shown
    assert summary.startswith("2 accounts may have something new") and "Scalable" not in summary
    assert "Get new for all 2, one by one" in summary
    assert round_ == ["Bank", "Card"]
    assert ["Needs a look", ["Bank", "Card"]] in sections
    assert ["Not started (1)", ["Scalable Capital"]] in sections


def test_a_shells_own_page_offers_record_steps_in_place_of_get_new(panel):
    shown = panel.evaluate("""(shell) => {
        ROWS = [row(shell, 'Scalable Capital', 'stopped', {last_outcome: 'stopped',
                    last_run: {action: 'all', result: {stopped: 1}}})];
        location.hash = '#/a/' + encodeURIComponent(shell) + '/primary';
        route();
        const body = $('a-body');
        return {text: body.textContent,
                does: [...body.querySelectorAll('.steps button')].map(b => b.dataset.do + ':' + (b.dataset.action || '')),
                resume: Boolean(body.querySelector('[data-action="resume"]')), dates: Boolean($('year'))};
    }""", SHELL)
    assert shown["does"] == ["run:login", "record:"]
    assert shown["resume"] is False and shown["dates"] is False
    assert "Not built yet" in shown["text"] and "Get new documents" not in shown["text"]
    assert "Leave the window open while you record your steps." in shown["text"]
    # Its Record steps opens Get help, where the recording is started.
    panel.evaluate("() => document.querySelector('.steps [data-do=\"record\"]').click()")
    assert panel.evaluate("() => $('dlg-support').open") is True
    panel.evaluate("() => $('dlg-support').querySelector('[data-do=\"rc-go\"]').click()")
    assert panel.evaluate("() => asked") == [["record", {}]]


def test_a_shells_own_page_after_a_restore_stopped_offers_no_restore_of_the_rest(panel):
    """A restore downloads again, which a shell cannot either."""
    shown = panel.evaluate("""([shell, built]) => {
        const left = {last_outcome: 'stopped', last_run: {action: 'all', redownload: true, result: {stopped: 1}}};
        ROWS = [row(shell, 'Scalable Capital', 'stopped', left), row(built, 'Bank', 'stopped', left)];
        const restores = app => {
            location.hash = '#/a/' + encodeURIComponent(app) + '/primary';
            route();
            return Boolean($('a-body').querySelector('[data-do="restore"]'));
        };
        return [restores(shell), restores(built)];
    }""", [SHELL, BUILT])
    assert shown == [False, True]


def test_a_built_providers_own_page_still_offers_get_new(panel):
    shown = panel.evaluate("""(built) => {
        location.hash = '#/a/' + encodeURIComponent(built) + '/primary';
        route();
        return [...$('a-body').querySelectorAll('.steps button')].map(b => b.dataset.do + ':' + (b.dataset.action || ''));
    }""", BUILT)
    assert shown == ["run:login", "run:all", "run:pilot", "run:discover"]


def test_a_run_knows_it_is_a_shells_from_its_row(panel):
    kept = panel.evaluate("""([shell, built]) => {
        startRun = window.realStart;
        startRun(rowFor(shell, 'primary'), 'login');
        const first = RUN.shell;
        finishRun('0');
        startRun(rowFor(built, 'primary'), 'login');
        return [first, RUN.shell];
    }""", [SHELL, BUILT])
    assert kept == [True, False]
