"""The home page's "may have something new" leaves out a gap a whole run
could not fill, and keeps an account that is due (#149).

Two accounts each stayed in the summary after every Get new for all, since
their only flag was a gap years back that no run filled.
These run the page's own script in Playwright's own headless Chromium,
against the real panel served on a free local port. Every setting and
folder is under a temp folder, and no browser of the person's is started.
The first tests run nothing. The rest press the page's own buttons, and what
they start is a stand-in app that ends clean, since what the page sends for a
gap row is what decides whether it can settle.
"""
import json
import socket
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
sync_api = pytest.importorskip("playwright.sync_api")


def _records(newest_days_ago, hole=None, count=8, every=30):
    out = {}
    newest = date.today() - timedelta(days=newest_days_ago)
    for i in range(count):
        if i == hole:
            continue
        d = (newest - timedelta(days=every * i)).isoformat()
        out["doc-%d" % i] = {"downloaded_ok": True, "state": "Completed", "date": d,
                             "pdf_filename": "Statements/%s Statement.pdf" % d, "updated_at": d}
    return out


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def base():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the panel did not start"
    yield "http://127.0.0.1:%d" % port
    server.should_exit = True
    thread.join(10)


# It notes what it was asked and says a clean run's counts, the way every app
# does. It reads no list. The records beside it say what the run took.
STANDIN = r'''
import json, os, sys
from pathlib import Path
with open(Path(__file__).resolve().parent / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
print("PAPERPULL_RUN_RESULT " + os.environ.get("PAPERPULL_RUN_MARK", "") + " " + json.dumps(
    {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0, "stopped": 0}),
    flush=True)
sys.exit(0)
'''


def _install(apps, name, provider, records, script_text="print('not run')\n"):
    folder = apps / name
    folder.mkdir(parents=True)
    script = name.split()[0].lower() + "_docs.py"
    (folder / script).write_text(script_text, encoding="utf-8")
    (folder / "storage.py").write_text(
        'SPEC = AppSpec(\n    provider="%s",\n    kind="DOCUMENT",\n)\n' % provider, encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    (folder / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    return folder


def _clean_all(gaps_left, ended="2026-11-06T16:01:00"):
    return {"action": "all", "account": "primary", "started": "2026-11-06T16:00:00",
            "ended": ended, "exit_code": 0, "closed": False,
            "result": {"manual_review": 0, "failed": 0, "validation_failures": 0,
                       "new_files": 0, "stopped": 0},
            "scope": [], "redownload": False, "saved": [], "gaps_left": gaps_left}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    # On macOS the settings file is under ~/Library, which none of the
    # variables above move, so the file itself is pointed into tmp_path, or
    # this would write the person's own settings.json.
    monkeypatch.setattr(app_module, "_settings_path", lambda: tmp_path / "settings" / "settings.json")
    app_module._write_settings({"terms_accepted": app_module.TERMS_VERSION})
    root = tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", str(root))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    app_module._RUNS.clear()
    return root


@pytest.fixture()
def apps(root):
    # Current by its newest document, with a gap 90 days back in the middle.
    gapped = _install(root, "Gapbank Statements", "Gapbank", _records(5, hole=3))
    # Due: its newest document is past its usual monthly interval.
    _install(root, "Duebank Statements", "Duebank", _records(45))
    return root, gapped


def _summary(tab, rows=2):
    tab.wait_for_function("() => ROWS && ROWS.length === %d" % rows)
    card = tab.locator(".summary")
    return card.inner_text() if card.count() else ""


def test_a_gap_a_whole_run_left_drops_out_and_a_due_account_stays(browser, base, apps):
    _root, gapped = apps
    keys = app_module._gaps_left(gapped)
    assert keys, "the made-up history has a gap"
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        before = _summary(tab)
        assert "Gapbank" in before and "Duebank" in before and "2 accounts" in before

        # Two whole runs, the second on another day, each left the gap.
        (gapped / app_module.RUN_LOG).write_text(json.dumps(
            [_clean_all(keys), _clean_all(keys, "2026-11-05T09:00:00")]), encoding="utf-8")
        tab.reload()
        after = _summary(tab)
        assert "Duebank" in after and "Gapbank" not in after, after
        assert "1 account " in after or after.startswith("1 account"), after
        # The row itself still says Possible gap and offers to look.
        tab.wait_for_selector("text=Possible gap")
    finally:
        context.close()


def test_a_gap_the_run_did_not_see_still_counts(browser, base, apps):
    _root, gapped = apps
    (gapped / app_module.RUN_LOG).write_text(json.dumps([_clean_all([])]), encoding="utf-8")
    context = browser.new_context()
    try:
        tab = context.new_page()
        tab.goto(base + "/")
        assert "Gapbank" in _summary(tab)
    finally:
        context.close()


# -- the page's own buttons, on a run that ends clean ---------------------------------

def _took_it_all(apps, name, provider, records):
    """An account that ends a run with its list read to its end and every
    document on it taken, as a stand-in's records have to say it did."""
    folder = _install(apps, name, provider, records, STANDIN)
    (folder / "discovery.json").write_text(json.dumps(
        {k: {"date": r["date"], "category": "Statement", "state": r["state"]}
         for k, r in records.items()}), encoding="utf-8")
    (folder / "last-listing.json").write_text(
        json.dumps({"complete": True, "at": "2031-01-15T09:00:00"}), encoding="utf-8")
    return folder


def _asked(folder):
    path = folder / "argv.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat() + "T09:00:00"


def _noted_the_day_before(folder):
    """A whole, clean run ended the day before that noted the gaps there now,
    so the next such run that notes them is the second, on another day."""
    keys = app_module._gaps_left(folder)
    assert keys
    (folder / app_module.RUN_LOG).write_text(json.dumps([_clean_all(keys, _yesterday())]),
                                             encoding="utf-8")


def _when_each_has_run(*folders, logged=1):
    """Each stand-in has been started and the panel has noted how it ended,
    the log then holding `logged` runs."""
    def ran(folder):
        return bool(_asked(folder)) and len(app_module._read_run_log(folder)) >= logged
    for _ in range(600):
        if all(ran(f) for f in folders) and not app_module._RUNS:
            return
        time.sleep(0.1)
    raise AssertionError("the runs did not end")


def _gap_row(folder):
    return next(r for r in app_module.account_rows() if r["app"] == folder.name)


def _dates_in(argv):
    return [a for a in argv if a in ("--year", "--start-date", "--end-date")]


def _first_page(browser, base, rows):
    context = browser.new_context()
    tab = context.new_page()
    tab.goto(base + "/")
    tab.wait_for_function("() => ROWS && ROWS.length === %d" % rows)
    return context, tab


def test_get_new_for_all_runs_each_gap_row_whole_and_settles_it(browser, base, root):
    """The path in #149. Two accounts stayed in the summary after every Get
    new for all, since the round sent the first gap's dates, and a run with
    dates cannot say a gap is one no run fills."""
    one = _took_it_all(root, "Gapone Statements", "Gapone", _records(5, hole=3))
    two = _took_it_all(root, "Gaptwo Statements", "Gaptwo", _records(6, hole=4))
    _noted_the_day_before(one)
    _noted_the_day_before(two)
    context, tab = _first_page(browser, base, 2)
    try:
        assert "2 accounts" in _summary(tab)
        tab.locator("[data-do=queue]").click()
        _when_each_has_run(one, two, logged=2)
        for folder in (one, two):
            assert _asked(folder) == [["--all", "--yes"]]
            entry = app_module._read_run_log(folder)[0]
            assert entry["scope"] == [] and entry["gaps_left"] == app_module._gaps_left(folder)
            assert entry["gaps_left"], "the made-up history has a gap"
            assert _gap_row(folder)["settled"] is True
        tab.goto(base + "/#/")
        tab.reload()
        after = _summary(tab)
        assert "Gapone" not in after and "Gaptwo" not in after, after
        assert tab.locator(".acct .chip", has_text="Possible gap").count() == 2
    finally:
        context.close()


def test_the_summarys_get_new_runs_a_gap_row_whole_and_settles_it(browser, base, root):
    """The first run notes the gap and the row stays, since the next run may
    take what this one could not. The next, a day on, settles it."""
    one = _took_it_all(root, "Gapone Statements", "Gapone", _records(5, hole=3))
    context, tab = _first_page(browser, base, 1)
    try:
        assert "Gapone" in _summary(tab, 1)
        tab.locator(".summary button.starts").click()
        _when_each_has_run(one)
        assert _asked(one) == [["--all", "--yes"]]
        log = app_module._read_run_log(one)
        assert log[0]["gaps_left"]
        tab.goto(base + "/#/")
        tab.reload()
        assert "Gapone" in _summary(tab, 1)
        log[0]["ended"] = _yesterday()
        (one / app_module.RUN_LOG).write_text(json.dumps(log), encoding="utf-8")
        tab.reload()
        tab.locator(".summary button.starts").click()
        _when_each_has_run(one, logged=2)
        assert _asked(one) == [["--all", "--yes"]] * 2
        tab.goto(base + "/#/")
        tab.reload()
        assert "Gapone" not in _summary(tab, 1)
    finally:
        context.close()


def test_look_for_them_keeps_its_dates_and_settles_nothing(browser, base, root):
    """The row's own button is for the gap, so it looks in the gap's dates,
    and a run over part of a history says nothing of the rest."""
    one = _took_it_all(root, "Gapone Statements", "Gapone", _records(5, hole=3))
    _noted_the_day_before(one)
    gap = _gap_row(one)["gaps"][0]
    context, tab = _first_page(browser, base, 1)
    try:
        tab.locator(".acct button.starts", has_text="Look for them").click()
        _when_each_has_run(one, logged=2)
        assert _asked(one) == [["--all", "--yes", "--start-date", gap["after"][:10],
                                "--end-date", gap["before"][:10]]]
        assert "gaps_left" not in app_module._read_run_log(one)[0]
        tab.goto(base + "/#/")
        tab.reload()
        assert "Gapone" in _summary(tab, 1)
    finally:
        context.close()


def test_a_gap_row_whose_run_left_something_stays_in_the_summary(browser, base, root):
    """The page runs it whole, the run ends clean, and its records say it
    left a listed document for the next run."""
    one = _took_it_all(root, "Gapone Statements", "Gapone", _records(5, hole=3))
    rows = json.loads((one / "discovery.json").read_text(encoding="utf-8"))
    rows["doc-3"] = {"date": (date.today() - timedelta(days=95)).isoformat(),
                     "category": "Statement", "state": "Discovered"}
    (one / "discovery.json").write_text(json.dumps(rows), encoding="utf-8")
    _noted_the_day_before(one)
    context, tab = _first_page(browser, base, 1)
    try:
        tab.locator(".summary button.starts").click()
        _when_each_has_run(one, logged=2)
        assert _asked(one) == [["--all", "--yes"]]
        assert "gaps_left" not in app_module._read_run_log(one)[0]
        tab.goto(base + "/#/")
        tab.reload()
        assert "Gapone" in _summary(tab, 1)
    finally:
        context.close()


def _stopped(folder):
    (folder / app_module.RUN_LOG).write_text(json.dumps(
        [{"action": "all", "account": "primary", "ended": "2031-01-15T09:00:00", "exit_code": 0,
          "closed": False, "result": {"stopped": 1}, "scope": [], "redownload": False, "saved": []}]),
        encoding="utf-8")


def test_a_round_sends_every_other_row_what_it_sent_before(browser, base, root):
    """A row that is due runs whole and one that stopped carries on. Only a
    gap row's dates went away."""
    due = _took_it_all(root, "Dueone Statements", "Dueone", _records(45))
    stopped = _took_it_all(root, "Stopone Statements", "Stopone", _records(5, hole=3))
    _stopped(stopped)
    context, tab = _first_page(browser, base, 2)
    try:
        tab.locator("[data-do=queue]").click()
        for _ in range(600):
            if _asked(due) and _asked(stopped) and not app_module._RUNS \
                    and len(app_module._read_run_log(stopped)) == 2:
                break
            time.sleep(0.1)
        assert _asked(due) == [["--all", "--yes"]]
        assert _asked(stopped) == [["--resume", "--yes"]]
    finally:
        context.close()


def test_the_summarys_button_on_a_stopped_row_still_carries_on(browser, base, root):
    stopped = _took_it_all(root, "Stopone Statements", "Stopone", _records(5, hole=3))
    _stopped(stopped)
    context, tab = _first_page(browser, base, 1)
    try:
        tab.locator(".summary button.starts").click()
        for _ in range(600):
            if _asked(stopped) and not app_module._RUNS \
                    and len(app_module._read_run_log(stopped)) == 2:
                break
            time.sleep(0.1)
        assert _asked(stopped) == [["--resume", "--yes"]]
    finally:
        context.close()
