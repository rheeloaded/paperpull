"""The home page's rows, one per provider and person, and the run log they read.

Each row says where an account stands, from the status reporter run on that
account's own folder, the panel's own log of the runs it started there, and
whether a run is going now. A run that did not finish puts its row first,
since the next step is to continue it. Only a run that downloads can leave a
row partway. The panel never says an account is signed in.

Everything is under tmp_path. Runs start a stand-in app with this Python,
the way the packaged build runs every app, and the stand-in does what a
file beside it says.
"""
import ast
import asyncio
import functools
import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
uvicorn = pytest.importorskip("uvicorn")
import run_result  # noqa: E402
import server_mode  # noqa: E402

# A stand-in app. It notes its arguments, then does what plan.json beside it
# says, waiting for a file when started with the flag plan says to wait on,
# so a test can hold it running, writing
# the list of files it saved, saying its counts the way every app does, and
# ending with the code it was given.
STANDIN = r'''
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
with open(here / "argv.jsonl", "a", encoding="utf-8") as f:
    print(json.dumps(sys.argv[1:]), file=f)
plan = json.loads((here / "plan.json").read_text(encoding="utf-8")) if (here / "plan.json").exists() else {}
mark = os.environ.get("PAPERPULL_RUN_MARK", "")
if "--rename" in sys.argv:
    # The move after a download run (#102), the app's own Rename. Until #103
    # every app's Rename wrote a run summary of its own, which left
    # new-this-run.txt listing nothing.
    if plan.get("rename_lists_nothing"):
        (here / "new-this-run.txt").write_text(
            "# 0 file(s) downloaded on this run:\n\n", encoding="utf-8")
    print("PAPERPULL_RUN_RESULT " + (mark + " " if mark else "") + json.dumps(
        {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}), flush=True)
    sys.exit(0)
print("Checking the connection to your signed-in browser...", flush=True)
if plan.get("wait") in sys.argv:
    for _ in range(400):
        if (here / "go").exists():
            break
        time.sleep(0.05)
saved = plan.get("saved", [])
if saved:
    (here / "new-this-run.txt").write_text(
        "# %d file(s) downloaded on this run:\n" % len(saved) + "\n".join(saved) + "\n",
        encoding="utf-8")
counts = {"manual_review": 0, "failed": 0, "validation_failures": 0,
          "new_files": len(saved), "stopped": plan.get("stopped", 0)}
counts.update(plan.get("counts", {}))
print("PAPERPULL_RUN_RESULT " + (mark + " " if mark else "") + json.dumps(counts), flush=True)
sys.exit(plan.get("code", 0))
'''


def _storage(provider, kind):
    return 'SPEC = AppSpec(\n    provider="%s",\n    kind=%s,\n)\n' % (provider, kind)


def _records(newest_days_ago, count=8, every=30, kind="DOCUMENT"):
    """Saved records, one every `every` days, the newest that many days ago."""
    out = {}
    newest = date.today() - timedelta(days=newest_days_ago)
    for i in range(count):
        d = (newest - timedelta(days=every * i)).isoformat()
        key = "doc-%d" % i
        rec = {"downloaded_ok": True, "state": "Completed",
               "pdf_filename": "Statements/%s Bank Statement.pdf" % d, "updated_at": d}
        rec["date" if kind == "DOCUMENT" else "purchase_date"] = d
        out[key] = rec
    return out


@pytest.fixture()
def root(tmp_path, monkeypatch):
    """An apps root holding a statements install with a second person, and a
    receipts install that has never run."""
    for name in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "settings"))
    apps = tmp_path / "apps"
    monkeypatch.setenv("APPS_ROOT", str(apps))
    monkeypatch.delenv("PAPERPULL_SERVER", raising=False)
    monkeypatch.setattr(app_module, "_SAMPLE", None)
    monkeypatch.setattr(app_module, "_is_packaged", lambda: True)
    monkeypatch.setattr(app_module, "_STATUS_MOD", None)
    app_module._RUNS.clear()

    bank = apps / "Bank Statements"
    bank.mkdir(parents=True)
    (bank / "bank_docs.py").write_text(STANDIN, encoding="utf-8")
    (bank / "storage.py").write_text(_storage("Bank", "DOCUMENT"), encoding="utf-8")
    (bank / "config.json").write_text(json.dumps({"output_dir": "."}), encoding="utf-8")
    (bank / "progress.json").write_text(json.dumps(_records(45)), encoding="utf-8")
    second = apps / "Bank Statements - second"
    second.mkdir()
    (second / "progress.json").write_text(json.dumps(_records(5)), encoding="utf-8")
    (bank / "config.second.json").write_text(
        json.dumps({"output_dir": "../Bank Statements - second"}), encoding="utf-8")

    shop = apps / "Shop Receipts"
    shop.mkdir()
    (shop / "shop_receipts.py").write_text(STANDIN, encoding="utf-8")
    (shop / "storage.py").write_text(_storage("Shop", "RECEIPT"), encoding="utf-8")
    yield apps
    app_module._RUNS.clear()


def _rows():
    return {(r["app"], r["account"]): r for r in app_module.account_rows()}


def _log(folder, *entries):
    (folder / app_module.RUN_LOG).write_text(json.dumps(list(entries)), encoding="utf-8")


# -- where each account stands -------------------------------------------------------

def test_every_provider_and_person_has_a_row_most_in_need_first(root):
    rows = app_module.account_rows()
    assert [(r["app"], r["account"], r["state"]) for r in rows] == [
        ("Bank Statements", "primary", "due"),
        ("Shop Receipts", "primary", "not_started"),
        ("Bank Statements", "second", "current"),
    ]
    bank = rows[0]
    assert bank["provider"] == "Bank" and bank["kind"] == "DOCUMENT"
    assert bank["documents"] == 8 and bank["age_days"] == 45 and bank["cadence"] == "monthly"
    assert rows[1]["provider"] == "Shop" and rows[1]["kind"] == "RECEIPT"
    assert rows[1]["documents"] == 0 and rows[1]["latest"] == []


def test_a_row_lists_its_newest_files_by_name_only(root):
    latest = _rows()[("Bank Statements", "primary")]["latest"]
    assert len(latest) == app_module.LATEST_SHOWN
    dates = [f["date"] for f in latest]
    assert dates == sorted(dates, reverse=True)
    assert all("/" not in f["name"] and "\\" not in f["name"] for f in latest)
    assert latest[0]["name"] == "%s Bank Statement.pdf" % latest[0]["date"]


def test_a_second_person_reads_their_own_folder(root):
    second = _rows()[("Bank Statements", "second")]
    assert second["age_days"] == 5 and second["state"] == "current"


def test_a_run_that_did_not_finish_puts_its_row_first(root):
    bank = root / "Bank Statements - second"
    for entry, outcome in (({"action": "all", "exit_code": 0, "result": {"stopped": 1}}, "stopped"),
                           ({"action": "pilot", "exit_code": 130}, "interrupted"),
                           ({"action": "resume", "exit_code": 2}, "failed"),
                           ({"action": "all", "exit_code": None, "closed": True}, "closed")):
        _log(bank, entry)
        row = _rows()[("Bank Statements", "second")]
        assert (row["state"], row["last_outcome"]) == ("stopped", outcome), entry
        assert app_module.account_rows()[0]["account"] == "second"


def test_a_resume_only_a_listing_carries_on_from_is_its_own_outcome(root):
    """Still a run that did not finish, so the row comes first, but one the
    page offers Get new for rather than Continue (#124)."""
    _log(root / "Bank Statements - second",
         {"action": "resume", "exit_code": 0, "result": {"stopped": 1, "list_not_read": 1}})
    row = _rows()[("Bank Statements", "second")]
    assert (row["state"], row["last_outcome"]) == ("stopped", "unlisted")
    assert app_module.account_rows()[0]["account"] == "second"
    _log(root / "Bank Statements - second",
         {"action": "resume", "exit_code": 0, "result": {"stopped": 1, "list_not_read": 0}})
    row = _rows()[("Bank Statements", "second")]
    assert (row["state"], row["last_outcome"]) == ("stopped", "stopped")


def _listing_note(folder, at, whole_at="", resume_ended=""):
    """The listing note an app keeps, and a Resume after it that read none."""
    note = {"complete": True, "at": at}
    if whole_at != "":
        note["whole_at"] = whole_at
    (folder / "last-listing.json").write_text(json.dumps(note), encoding="utf-8")
    if resume_ended:
        (folder / "run-summary.txt").write_text(
            "Mode: resume\nRun end: %s\n" % resume_ended, encoding="utf-8")
        _log(folder, {"action": "resume", "exit_code": 0, "ended": resume_ended,
                      "result": {"stopped": 0, "new_files": 0}})


def test_a_continue_with_nothing_to_take_is_no_check(panel, root):
    """A Continue after every listed document was saved reads no list, so
    the card says when the list was last read, not when the Continue ran,
    and the last run is still said as the run it was (#148)."""
    bank = root / "Bank Statements - second"
    weeks_ago = (date.today() - timedelta(days=21)).isoformat() + "T09:00:00"
    today = date.today().isoformat() + "T10:00:00"
    _listing_note(bank, weeks_ago, weeks_ago, resume_ended=today)
    row = _rows()[("Bank Statements", "second")]
    assert (row["state"], row["checked"], row["ran"]) == ("current", weeks_ago, today)
    shown = panel.evaluate("(row) => present(row)", json.loads(json.dumps(row, default=str)))
    said_then = panel.evaluate("(iso) => when(iso)", weeks_ago)
    said_today = panel.evaluate("(iso) => when(iso)", today)
    assert shown["say"].endswith("checked " + said_then), shown
    assert said_today not in shown["say"]


@pytest.mark.parametrize("complete, whole_at, checked", [
    (True, "", "at"), (False, "", None), (True, None, None)],
    ids=["older note, whole", "older note, stopped", "never read whole"])
def test_a_card_says_checked_only_for_a_list_read_whole(panel, root, complete, whole_at, checked):
    bank = root / "Bank Statements - second"
    at = (date.today() - timedelta(days=9)).isoformat() + "T09:00:00"
    _listing_note(bank, at, whole_at)
    if not complete:
        (bank / "last-listing.json").write_text(json.dumps({"complete": False, "at": at}),
                                                encoding="utf-8")
    row = _rows()[("Bank Statements", "second")]
    assert row["checked"] == (at if checked else None)
    shown = panel.evaluate("(row) => present(row)", json.loads(json.dumps(row, default=str)))
    assert ("checked" in shown["say"]) is bool(checked), shown


def test_a_stopped_run_from_a_terminal_still_says_when_it_ran(panel, root):
    """With nothing in the panel's log, the last run is the run summary's."""
    bank = root / "Bank Statements - second"
    ended = (date.today() - timedelta(days=3)).isoformat() + "T10:00:00"
    (bank / "run-summary.txt").write_text("Mode: all\nRun end: %s\n" % ended, encoding="utf-8")
    row = dict(_rows()[("Bank Statements", "second")], state="stopped", last_outcome="unlisted")
    shown = panel.evaluate("(row) => present(row)", json.loads(json.dumps(row, default=str)))
    assert ("The last run on " + panel.evaluate("(iso) => when(iso)", ended)) in shown["say"]


def test_a_clean_run_after_a_stop_clears_it(root):
    _log(root / "Bank Statements - second",
         {"action": "all", "exit_code": 0, "result": {"stopped": 0, "attention": False}},
         {"action": "all", "exit_code": 0, "result": {"stopped": 1}})
    row = _rows()[("Bank Statements", "second")]
    assert (row["state"], row["last_outcome"]) == ("current", "")


def test_only_a_run_that_downloads_can_leave_a_row_partway(root):
    """A Discover or a Login that stops has nothing to continue."""
    _log(root / "Bank Statements - second",
         {"action": "discover", "exit_code": 1},
         {"action": "login", "exit_code": 0, "closed": True})
    row = _rows()[("Bank Statements", "second")]
    assert row["state"] == "current" and row["last_run"] is None
    assert [e["action"] for e in row["runs"]] == ["discover", "login"]


def test_what_a_run_left_to_look_at_comes_before_how_current(root):
    _log(root / "Bank Statements - second",
         {"action": "all", "exit_code": 0, "result": {"stopped": 0, "attention": True,
                                                      "manual_review": 1}})
    assert _rows()[("Bank Statements", "second")]["state"] == "attention"


@pytest.fixture()
def panel():
    """The panel's own page in Playwright's own Chromium, served from an
    invented address with nothing else answered, so only its functions are
    asked here. One per test, since Playwright's loop left running would
    stop the later tests here that run one of their own. A test asks for it
    before `root`, which moves LOCALAPPDATA, where Windows keeps Chromium."""
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=[
                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                "--disable-component-update", "--no-first-run"])
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
        yield tab
        chromium.close()


def _alike_run(new_files=1):
    """A run as the panel logs it, from a result line that counted two
    documents of one type on one date and nothing else."""
    mark = run_result.new_mark()
    said = run_result.PREFIX + mark + " " + json.dumps({"manual_review": 0, "failed": 0,
                                                        "validation_failures": 0,
                                                        "new_files": new_files, "alike": 2})
    return {"action": "all", "exit_code": 0, "result": run_result.parse(said, mark)}


@pytest.mark.parametrize("newest_days_ago, state, chip", [
    (5, "current", "Up to date"), (45, "due", "New one likely"), (100, "overdue", "Overdue")])
def test_documents_left_alike_leave_the_row_as_it_would_be_without_them(panel, root, newest_days_ago,
                                                                        state, chip):
    """Alpaca lists two documents of one type on one date on every run and
    never saves them, so every run counts them again. A run that counted
    them leaves the row up to date, due or overdue, with Get new offered,
    rather than needing a look for good."""
    bank = root / "Bank Statements - second"
    (bank / "progress.json").write_text(json.dumps(_records(newest_days_ago)), encoding="utf-8")
    assert _rows()[("Bank Statements", "second")]["state"] == state
    _log(bank, _alike_run())
    row = _rows()[("Bank Statements", "second")]
    assert (row["state"], row["last_outcome"]) == (state, "")
    shown = panel.evaluate("(row) => present(row)", json.loads(json.dumps(row, default=str)))
    assert shown["chip"]["text"] == chip and shown["act"]["label"] == "Get new"


@pytest.mark.parametrize("saved, new_files, title, said", [
    (["2026-09-30 Bank Statement.pdf"], 1, "1 new document saved", "Finished. 2 documents"),
    ([], 0, "Nothing new", "Everything else Bank lists in these dates is already saved. 2 documents")])
def test_a_run_that_counted_documents_alike_names_them_and_finishes_clean(panel, saved, new_files,
                                                                          title, said):
    o = panel.evaluate("""([result, saved]) => {
        Object.assign(RUN, {result, code: '0', action: 'all', again: false, refused: '', saved,
                            provider: 'Bank', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", [_alike_run(new_files)["result"], saved])
    assert (o["tone"], o["title"]) == ("ok", title) and not o.get("attention")
    assert said in o["say"]
    assert ("that share a type and a date with another could not be told apart and were left "
            "unsaved. Take any you need from Bank's own page.") in o["say"]


def _counted(**counts):
    """A run's own result, as the panel reads it from the run's marked line."""
    mark = run_result.new_mark()
    said = run_result.PREFIX + mark + " " + json.dumps(dict(
        {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}, **counts))
    return run_result.parse(said, mark)


def _outcome(panel, result, saved, action="all"):
    return panel.evaluate("""([result, saved, action]) => {
        Object.assign(RUN, {result, code: '0', action, again: false, refused: '', saved,
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", [result, saved, action])


@pytest.mark.parametrize("action", ["pilot", "all", "resume"])
@pytest.mark.parametrize("saved", [[], ["2020-10-31 Citi Statement.pdf"]])
def test_a_run_that_saved_documents_never_says_nothing_new(panel, action, saved):
    """The count is the run's own, from its result. The names come from its
    new-this-run.txt, which can name fewer (two files of one name are one
    name there) or none, as when a step after the run had replaced it, which
    made a Citi run that saved 23 requested statements say Nothing new (#103).
    The home page's line for the run counts the same way."""
    o = _outcome(panel, _counted(new_files=23), saved, action)
    assert (o["tone"], o["title"]) == ("ok", "23 new documents saved")
    entry = {"action": action, "exit_code": 0, "result": _counted(new_files=23), "saved": saved}
    assert ", 23 new documents</span>" in panel.evaluate("(e) => runLine(e)", entry)
    o = _outcome(panel, _counted(new_files=23, failed=1), saved, action)
    assert o["title"] == "23 new documents saved, some need a look"


@pytest.mark.parametrize("stop, code, title, signin, resume", [
    ("needs_you", "0", "Citi needed you partway", True, True),
    ("page", "0", "Citi's page was not what PaperPull expected", False, False),
    ("slow", "1", "Citi was too slow to answer", False, True),
    ("error", "1", "PaperPull ran into something it did not expect", False, True),
    ("", "0", "Stopped before finishing", True, True),
])
def test_a_stop_says_why_and_whose_it_is_to_fix(panel, stop, code, title, signin, resume):
    """A changed page used to read as a sign-out, so the person signed in
    and pressed Continue, which stopped at the same place again. Only a
    stop a sign-in can fix offers one, and no stop guesses a sign-out."""
    o = panel.evaluate("""([result, code]) => {
        Object.assign(RUN, {result, code, action: 'all', again: false, refused: '', saved: [],
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", [dict(_counted(stopped=1), stop=stop), code])
    assert o["title"] == title
    assert "may have signed you out" not in o["say"] and "exited with code" not in o["say"]
    assert (o.get("signin") is not False) is signin and bool(o.get("resume")) is resume
    if stop == "page":
        assert "for PaperPull to fix, not you" in o["say"]


def test_a_list_left_unread_keeps_its_own_next_step_whatever_stopped_it(panel):
    o = panel.evaluate("""(result) => {
        Object.assign(RUN, {result, code: '0', action: 'resume', again: false, refused: '', saved: [],
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", dict(_counted(stopped=1, list_not_read=1), stop="page"))
    assert o.get("relist") and "was not read to its end" in o["say"]


@pytest.mark.parametrize("action, code, refused, tone, title, signin", [
    ("login", "5", "", "bad", "No sign-in window opened", False),
    ("record", "6", "", "info", "Nothing was recorded", True),
    ("all", "1", "Citi is already running for this account, in another tab or window.",
     "bad", "This run did not start", False),
])
def test_what_did_not_happen_is_never_said_to_have(panel, action, code, refused, tone, title, signin):
    """A sign-in with no window, an empty or refused recording and a run
    the server would not start each say so, and never 'Sign-in window
    opened', 'Recording saved' or an exit code."""
    o = panel.evaluate("""([action, code, refused]) => {
        Object.assign(RUN, {result: null, code, action, again: false, refused, saved: [],
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", [action, code, refused])
    assert (o["tone"], o["title"]) == (tone, title)
    assert "exited with code" not in o["say"]
    assert bool(o.get("signin")) is signin and not o.get("resume")


def test_a_run_that_saved_nothing_still_says_so(panel):
    o = _outcome(panel, _counted(), [])
    assert (o["tone"], o["title"]) == ("ok", "Nothing new")
    assert _outcome(panel, _counted(failed=1), [])["title"] == "Finished, some need a look"
    # A log in the run's folder can hold anything, and an odd count in it
    # is no count.
    for odd in ("23", -1, 2.5, None, [3]):
        entry = {"action": "all", "exit_code": 0, "result": {"new_files": odd}, "saved": []}
        assert ", nothing new</span>" in panel.evaluate("(e) => runLine(e)", entry), odd
    entry = {"action": "all", "exit_code": 0, "result": {}, "saved": ["a.pdf", "b.pdf"]}
    assert ", 2 new documents</span>" in panel.evaluate("(e) => runLine(e)", entry)


def test_a_broken_log_is_no_log(root):
    (root / "Bank Statements" / app_module.RUN_LOG).write_text("{not json", encoding="utf-8")
    assert _rows()[("Bank Statements", "primary")]["runs"] == []
    (root / "Bank Statements" / app_module.RUN_LOG).write_text('[1, "x", {"action": "all"}]',
                                                               encoding="utf-8")
    assert _rows()[("Bank Statements", "primary")]["runs"] == [{"action": "all"}]


@pytest.mark.parametrize("bad", [5, ["a"], {"x": 1}])
def test_a_config_whose_folder_is_not_text_takes_no_row_down(root, bad):
    """A config written by hand can hold a number or a list for output_dir.
    That person's row says its status could not be read, every other row
    is as before, and their folder is never taken to be the first person's."""
    (root / "Bank Statements" / "config.second.json").write_text(
        json.dumps({"output_dir": bad}), encoding="utf-8")
    rows = _rows()
    assert rows[("Bank Statements", "second")]["state"] == "nostatus"
    assert rows[("Bank Statements", "second")]["latest"] == []
    assert rows[("Bank Statements", "primary")]["state"] == "due"
    assert rows[("Shop Receipts", "primary")]["state"] == "not_started"
    # Refused where the folder is worked out, never taken to be the
    # install's own, which is the first person's, and the server hands
    # nothing of that person's on to a plug-in.
    with pytest.raises(ValueError):
        server_mode.output_root(root / "Bank Statements", "second")
    (root / "Bank Statements" / "new-this-run.txt").write_text("Statements/x.pdf\n", encoding="utf-8")
    assert server_mode.new_files(root / "Bank Statements", "second", 0) == []


def test_without_the_status_reader_no_account_is_called_not_started(root, monkeypatch):
    monkeypatch.setattr(app_module, "_status_module", lambda: None)
    states = {(r["app"], r["account"]): r["state"] for r in app_module.account_rows()}
    assert set(states.values()) == {"nostatus"}
    assert app_module.api_accounts()["status_available"] is False


def test_nothing_says_an_account_is_signed_in(root):
    for row in app_module.account_rows():
        assert not any("sign" in key for key in row)
        assert row["state"] in app_module.STATE_ORDER


# -- the run log, written by real runs over HTTP --------------------------------------

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
    yield port
    server.should_exit = True
    thread.join(10)


def run(port, body):
    req = urllib.request.Request("http://127.0.0.1:%d/api/run" % port, method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        # No proxy, the panel is on this computer.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")


def events(stream, name):
    found = []
    for block in stream.split("\n\n"):
        lines = block.split("\n")
        if ("event: %s" % name) in lines:
            found.append("\n".join(line[6:] for line in lines if line.startswith("data: ")))
    return found


def _plan(folder, **plan):
    (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")


def _settled(timeout=15):
    for _ in range(int(timeout / 0.05)):
        if not app_module._RUNS:
            return True
        time.sleep(0.05)
    return False


def test_a_run_says_what_it_saved_and_logs_it(base, root):
    bank = root / "Bank Statements"
    _plan(bank, saved=["Statements/2026-09-30 Bank Statement.pdf", "Statements/2026-10-31 Bank Statement.pdf"])
    out = run(base, {"app": "Bank Statements", "action": "all"})
    assert events(out, "done") == ["0"]
    assert [json.loads(s) for s in events(out, "saved")] == [
        ["2026-09-30 Bank Statement.pdf", "2026-10-31 Bank Statement.pdf"]]
    log = app_module._read_run_log(bank)
    assert len(log) == 1
    entry = log[0]
    assert entry["action"] == "all" and entry["account"] == "primary" and entry["exit_code"] == 0
    assert entry["closed"] is False and entry["redownload"] is False and entry["scope"] == []
    assert entry["result"]["new_files"] == 2
    assert entry["saved"] == ["2026-09-30 Bank Statement.pdf", "2026-10-31 Bank Statement.pdf"]
    assert entry["started"] <= entry["ended"]
    row = _rows()[("Bank Statements", "primary")]
    assert row["last_run"] == entry and row["last_outcome"] == "" and row["running"] is None


def test_a_run_moved_to_its_documents_folder_still_says_what_it_saved(base, root):
    """appchamp's Citi run saved 23 requested statements and its page said
    Nothing new (#103). His account had a documents folder, so the panel
    moved what the run saved there with the app's own Rename, which wrote
    an empty new-this-run.txt, and the panel read the list after that. It
    is read as the run ends now, before anything else runs."""
    bank = root / "Bank Statements"
    (bank / "config.json").write_text(json.dumps({
        "output_dir": ".", "documents_dir": str(root.parent / "Watched" / "Bank Statements")}),
        encoding="utf-8")
    names = ["2020-10-31 Bank Statement.pdf", "2020-12-31 Bank Statement.pdf"]
    _plan(bank, saved=["Statements/" + n for n in names], rename_lists_nothing=True)
    out = run(base, {"app": "Bank Statements", "action": "all"})
    assert events(out, "done") == ["0"]
    starts = [json.loads(line) for line in (bank / "argv.jsonl").read_text(encoding="utf-8").splitlines()]
    assert starts == [["--all", "--yes"], ["--rename", "--apply"]]
    assert "0 file(s)" in (bank / "new-this-run.txt").read_text(encoding="utf-8")
    assert [json.loads(s) for s in events(out, "saved")] == [names]
    assert [json.loads(s)["new_files"] for s in events(out, "result")] == [2]
    assert app_module._read_run_log(bank)[0]["saved"] == names


def test_an_old_list_of_new_files_is_never_this_runs(base, root):
    bank = root / "Bank Statements"
    (bank / "new-this-run.txt").write_text("# 1 file(s)\nStatements/old.pdf\n", encoding="utf-8")
    past = time.time() - 3600
    os.utime(bank / "new-this-run.txt", (past, past))
    _plan(bank)
    out = run(base, {"app": "Bank Statements", "action": "pilot", "year": "2026"})
    assert [json.loads(s) for s in events(out, "saved")] == [[]]
    entry = app_module._read_run_log(bank)[0]
    assert entry["saved"] == [] and entry["scope"] == ["--year", "2026"]


def test_a_run_that_stopped_leaves_its_row_partway(base, root):
    bank = root / "Bank Statements"
    _plan(bank, stopped=1)
    run(base, {"app": "Bank Statements", "action": "all"})
    row = _rows()[("Bank Statements", "primary")]
    assert (row["state"], row["last_outcome"]) == ("stopped", "stopped")


def test_a_second_run_of_one_account_waits_for_the_first(base, root):
    bank = root / "Bank Statements"
    _plan(bank, wait="--pilot")
    first = {}
    t = threading.Thread(target=lambda: first.setdefault(
        "out", run(base, {"app": "Bank Statements", "action": "pilot"})))
    t.start()
    for _ in range(400):
        if ("Bank Statements", "primary") in app_module._RUNS:
            break
        time.sleep(0.05)
    running = _rows()[("Bank Statements", "primary")]["running"]
    assert running and running["action"] == "pilot"
    second = run(base, {"app": "Bank Statements", "action": "all"})
    assert "already running for this account" in second and events(second, "done") == ["1"]
    # Said as a run that did not start, not as one that began and failed.
    refused = events(second, "refused")
    assert len(refused) == 1 and "already running for this account" in refused[0]
    # Another person on the same app is not held up.
    other = run(base, {"app": "Bank Statements", "account": "second", "action": "discover"})
    assert "already running" not in other
    (bank / "go").write_text("", encoding="utf-8")
    t.join(30)
    assert events(first["out"], "done") == ["0"]
    starts = [json.loads(line) for line in (bank / "argv.jsonl").read_text(encoding="utf-8").splitlines()]
    assert starts == [["--pilot"], ["--discover", "--config", "config.second.json"]]
    assert _settled() and "Bank Statements" not in app_module._RUNNING


def test_a_folder_that_cannot_be_read_never_leaves_a_run_claimed(base, root):
    """The claim on an account is made only once its folder is known, so a
    config that names no folder cannot leave the account running forever."""
    bank = root / "Bank Statements"
    (bank / "config.second.json").write_text(json.dumps({"output_dir": 7}), encoding="utf-8")
    _plan(bank)
    for _ in range(2):
        out = run(base, {"app": "Bank Statements", "account": "second", "action": "discover"})
        assert "already running" not in out and events(out, "done") == ["0"]
    assert _settled() and app_module._RUNS == {}
    assert _rows()[("Bank Statements", "second")]["running"] is None


def test_a_page_closed_mid_run_is_logged_as_stopped(base, root):
    bank = root / "Bank Statements"
    _plan(bank, wait="--all")
    conn = http.client.HTTPConnection("127.0.0.1", base, timeout=30)
    conn.request("POST", "/api/run", body=json.dumps({"app": "Bank Statements", "action": "all"}),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    for _ in range(400):
        if ("Bank Statements", "primary") in app_module._RUNS:
            break
        time.sleep(0.05)
    conn.sock.close()
    conn.close()
    assert _settled(30), "the run was not ended when its page went away"
    entry = app_module._read_run_log(bank)[0]
    assert entry["closed"] is True and entry["exit_code"] is None
    row = _rows()[("Bank Statements", "primary")]
    assert (row["state"], row["last_outcome"]) == ("stopped", "closed")


# -- showing an account's folder -------------------------------------------------------

class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _pdf(path, age):
    """A PDF written `age` seconds ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n")
    when = time.time() - age
    os.utime(path, (when, when))
    return path


def _opened(monkeypatch):
    opened = []

    class Popen:
        def __init__(self, cmd, *a, **k):
            opened.append(Path(cmd[-1]).resolve())

    monkeypatch.setattr(app_module.subprocess, "Popen", Popen)
    return opened


def test_open_folder_shows_the_documents_not_the_programs_beside_them(root, monkeypatch):
    """The account's own folder holds its script, config and records, and
    the PDFs one folder down, so Open folder opens the one holding them."""
    own = root / "Bank Statements"
    _pdf(own / "Statements" / "2024" / "march.pdf", 100)
    # Newer, but none of these is where its documents are.
    for records in ("Logs", "Diagnostics", "Backups", "Manual Review", ".cache"):
        _pdf(own / records / "x.pdf", 1)
    opened = _opened(monkeypatch)
    meta = app_module.discover_apps()["Bank Statements"]
    assert app_module._where_documents_are(meta, "primary") == own / "Statements"
    asyncio.run(app_module.api_reveal(_Req({"app": "Bank Statements"})))
    assert opened == [(own / "Statements").resolve()]
    assert app_module.api_saved_in("Bank Statements", "primary") == {"folder": str(own / "Statements")}


def test_open_folder_follows_the_newest_document_into_a_documents_folder(root, tmp_path, monkeypatch):
    """Once a documents folder is set, only what is saved from then on goes
    there, so it is shown once it holds the newest document, and not before."""
    own, docs = root / "Bank Statements", tmp_path / "Documents" / "Bank"
    docs.mkdir(parents=True)
    _pdf(own / "Statements" / "old.pdf", 500)
    monkeypatch.setattr(app_module, "_documents_of", lambda meta, account: str(docs))
    meta = app_module.discover_apps()["Bank Statements"]
    assert app_module._where_documents_are(meta, "primary") == own / "Statements"
    _pdf(docs / "Statements" / "new.pdf", 10)
    assert app_module._where_documents_are(meta, "primary") == docs


def test_with_no_document_yet_it_is_the_documents_folder_or_the_accounts_own(root, tmp_path, monkeypatch):
    meta = app_module.discover_apps()["Bank Statements"]
    assert app_module._where_documents_are(meta, "primary") == root / "Bank Statements"
    docs = tmp_path / "Documents"
    docs.mkdir()
    monkeypatch.setattr(app_module, "_documents_of", lambda meta, account: str(docs))
    assert app_module._where_documents_are(meta, "primary") == docs


@pytest.mark.skipif(sys.platform == "win32", reason="links need privileges on Windows")
def test_a_link_in_the_folder_is_never_followed_to_find_documents(root, tmp_path, monkeypatch):
    own = root / "Bank Statements"
    _pdf(own / "Statements" / "mine.pdf", 100)
    _pdf(tmp_path / "elsewhere" / "newer.pdf", 1)
    (own / "Linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    meta = app_module.discover_apps()["Bank Statements"]
    assert app_module._where_documents_are(meta, "primary") == own / "Statements"


def test_a_support_file_and_what_was_set_aside_open_their_own_folders(root, monkeypatch):
    own = root / "Bank Statements"
    _pdf(own / "Statements" / "a.pdf", 100)
    (own / "Diagnostics").mkdir()
    opened = _opened(monkeypatch)
    for what in ("diagnostics", "aside", "records"):
        asyncio.run(app_module.api_reveal(_Req({"app": "Bank Statements", "what": what})))
    # Nothing was set aside, so its folder is not there, and the account's is shown.
    assert opened == [(own / "Diagnostics").resolve(), own.resolve(), own.resolve()]
    for what in ("../..", "/etc", "Statements"):
        with pytest.raises(app_module.HTTPException) as e:
            asyncio.run(app_module.api_reveal(_Req({"app": "Bank Statements", "what": what})))
        assert e.value.status_code == 400


def test_a_run_that_saved_documents_says_where_and_offers_to_show_them(panel):
    """Where the documents went was asked where it was answered least, on
    the page that lists them."""
    js = panel.evaluate("() => [whereSaved.toString(), finishRun.toString(), renderRun.toString()]")
    assert "/api/saved-in?" in js[0]
    assert "savedCount(RUN.result, RUN.saved || []) && !SERVER && !inSample()) whereSaved(" in js[1]
    shown = panel.evaluate("""() => {
        const r = {app: 'Bank Statements', account: 'primary', provider: 'Bank', kind: 'DOCUMENT', state: 'current',
                   runnable: true, documents: 1, gaps: [], latest: [], runs: []};
        ROWS = [r];
        Object.assign(RUN, {state: 'done', app: r.app, account: r.account, provider: r.provider, kind: r.kind,
                            action: 'all', scope: {year: '', start: '', end: ''}, again: false, lines: [], result: null,
                            saved: ['a.pdf'], code: '0',
                            refused: '', failure: false, startedAt: new Date(), endedAt: new Date(),
                            savedIn: '/Users/me/Documents/Bank/Statements'});
        RUN.outcome = runOutcome();
        renderRun();
        const keep = document.querySelector('#view-run .keepopen');
        return [keep.innerText, keep.querySelector('button').dataset.what || ''];
    }""")
    assert "Saved to /Users/me/Documents/Bank/Statements" in shown[0] and "Open folder" in shown[0]
    assert shown[1] == "", "the documents, which reveal shows unless told otherwise"


def test_open_folder_shows_only_the_accounts_own_folder(root, monkeypatch):
    opened = []

    class Popen:
        def __init__(self, cmd, *a, **k):
            opened.append(cmd)

    monkeypatch.setattr(app_module.subprocess, "Popen", Popen)
    reveal = lambda body: asyncio.run(app_module.api_reveal(_Req(body)))  # noqa: E731
    assert reveal({"app": "Bank Statements", "account": "second"}) == {"ok": True}
    assert reveal({"app": "Bank Statements"}) == {"ok": True}
    assert [Path(cmd[-1]).resolve() for cmd in opened] == [
        (root / "Bank Statements - second").resolve(), (root / "Bank Statements").resolve()]
    for body in ({"app": "Bank Statements", "account": "nobody"}, {"app": "../x"},
                 {"app": "Bank Statements", "account": "../../etc"}):
        with pytest.raises(app_module.HTTPException) as e:
            reveal(body)
        assert e.value.status_code == 404
    assert len(opened) == 2


# -- a second person's Diagnostics folder -----------------------------------------

def test_stop_recording_reaches_a_second_persons_own_folder(root):
    """A second person's recording waits in their own folder, so Stop has to
    write there, and only for an account the panel itself found."""
    stop = lambda body: asyncio.run(app_module.api_record_stop(_Req(body)))  # noqa: E731
    assert stop({"app": "Bank Statements", "account": "second"})["stopping"] is True
    assert (root / "Bank Statements - second" / "Diagnostics" / ".stop-recording").is_file()
    assert not (root / "Bank Statements" / "Diagnostics" / ".stop-recording").exists()
    assert stop({"app": "Bank Statements"})["stopping"] is True
    assert (root / "Bank Statements" / "Diagnostics" / ".stop-recording").is_file()
    for account in ("nobody", "../x", "second/../../x"):
        with pytest.raises(app_module.HTTPException) as e:
            stop({"app": "Bank Statements", "account": account})
        assert e.value.status_code == 404


def test_a_second_persons_failure_file_is_offered_for_them(root):
    diag = root / "Bank Statements - second" / "Diagnostics"
    diag.mkdir()
    (diag / "failure-pilot-20261012-100000.json").write_text("{}", encoding="utf-8")
    assert app_module.api_failure_latest("Bank Statements", "second") == {
        "found": True, "name": "failure-pilot-20261012-100000.json"}
    assert app_module.api_failure_latest("Bank Statements") == {"found": False}
    with pytest.raises(app_module.HTTPException) as e:
        app_module.api_failure_latest("Bank Statements", "nobody")
    assert e.value.status_code == 404


def test_a_broken_second_config_never_reaches_the_first_persons_diagnostics(root):
    """Guessing the install's folder for a config that names none would
    offer the first person's failure file to the second, and end the first
    person's recording from the second's Stop."""
    (root / "Bank Statements" / "config.second.json").write_text(
        json.dumps({"output_dir": 7}), encoding="utf-8")
    first = root / "Bank Statements" / "Diagnostics"
    first.mkdir()
    (first / "failure-pilot-20261012-100000.json").write_text("{}", encoding="utf-8")
    assert app_module.api_failure_latest("Bank Statements", "second") == {"found": False}
    assert app_module.api_failure_latest("Bank Statements")["found"] is True
    with pytest.raises(app_module.HTTPException) as e:
        asyncio.run(app_module.api_record_stop(_Req({"app": "Bank Statements", "account": "second"})))
    assert e.value.status_code == 404
    assert not (first / ".stop-recording").exists()


def test_a_run_that_ended_by_itself_before_its_page_closed_keeps_its_code(base, root, monkeypatch):
    """The page can go while the panel is still finishing a run that has
    already ended, during the Paperless copy on the server say. That run
    finished, and its row must not say it stopped partway. Here the panel
    is held once its wait for the app has returned, and the page goes only
    then, never after a guessed time, since a busy machine can keep the
    app going well past one."""
    import anyio
    bank = root / "Bank Statements"
    _plan(bank, saved=["Statements/2026-09-30 Bank Statement.pdf"])
    real = app_module.to_thread
    ended = threading.Event()
    held = []

    class Held:
        @staticmethod
        async def run_sync(fn, *args, **kwargs):
            out = await real.run_sync(fn, *args, **kwargs)
            if getattr(fn, "__name__", "") == "wait":
                ended.set()
                # Held until the page going ends it. The limit only keeps a
                # panel that never hears of it from hanging the test.
                try:
                    await anyio.sleep(20)
                except anyio.get_cancelled_exc_class():
                    held.append("ended by the page")
                    raise
                held.append("ran out")
            return out
    monkeypatch.setattr(app_module, "to_thread", Held)
    conn = http.client.HTTPConnection("127.0.0.1", base, timeout=30)
    conn.request("POST", "/api/run", body=json.dumps({"app": "Bank Statements", "action": "all"}),
                 headers={"Content-Type": "application/json"})
    conn.getresponse()
    assert ended.wait(30), "the app did not end"
    conn.sock.close()
    conn.close()
    assert _settled(30)
    # The page went while the panel was still finishing, not after.
    assert held == ["ended by the page"]
    log = app_module._read_run_log(bank)
    assert len(log) == 1
    assert log[0]["exit_code"] == 0 and log[0]["closed"] is False
    assert log[0]["result"]["new_files"] == 1
    assert _rows()[("Bank Statements", "primary")]["last_outcome"] == ""


@pytest.mark.parametrize("action", ["all", "pilot", "discover", "resume"])
def test_a_run_with_nobody_signed_in_says_sign_in_first(panel, action):
    """Get new before Open sign-in window read as a crash with an exit code,
    said 'Sign in again' to somebody who never had, and offered Continue
    for a run that never started."""
    o = panel.evaluate("""(action) => {
        Object.assign(RUN, {result: null, code: NOT_SIGNED_IN, action, again: false, refused: '', saved: [],
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""", action)
    assert (o["tone"], o["title"]) == ("info", "Sign in first")
    assert "exited with code" not in o["say"] and "nothing was downloaded" in o["say"]
    assert o["signin"] and o["first"] and o["rerun"] and not o.get("resume")


def test_once_signed_in_the_same_run_is_the_next_step_over_the_same_dates(panel):
    step = panel.evaluate("""() => rerunStep({action: 'pilot', scope: {year: '2024', start: '', end: ''}}, 'k', '2')""")
    assert 'data-action="pilot"' in step and 'data-year="2024"' in step and ">2</div>" in step
    # After a sign-in, Get new over all dates, as the row's own button runs.
    step = panel.evaluate("""() => rerunStep({action: 'login', scope: {year: '2024'}}, 'k', '1')""")
    assert 'data-action="all"' in step and "data-year" not in step and "Get new documents" in step
    assert 'btn btn-p' in step and 'stepnum on' in step
    # After a sign-in still to do, which then carries the weight itself.
    step = panel.evaluate("""() => rerunStep({action: 'all', scope: {}}, 'k', '2', true)""")
    assert 'btn btn-s' in step and 'stepnum on' not in step


def test_a_sign_in_window_that_opened_goes_straight_on_to_get_new(panel):
    o = panel.evaluate("""() => {
        Object.assign(RUN, {result: null, code: '0', action: 'login', again: false, refused: '', saved: [],
                            provider: 'Citi', kind: 'DOCUMENT', lines: []});
        return runOutcome();
    }""")
    assert o["title"] == "Sign-in window opened" and o["rerun"] and o["signin"] is False


def test_a_run_with_nobody_signed_in_is_not_a_stop_to_continue():
    entry = {"action": "all", "exit_code": app_module.NOT_SIGNED_IN, "result": None}
    assert app_module._last_outcome(entry) == "signin"
    assert app_module._account_state(None, "signin", []) == "signin"
    assert app_module.STATE_ORDER.index("signin") < app_module.STATE_ORDER.index("not_started")


def test_an_account_not_started_offers_to_sign_in_not_to_open_its_page(panel):
    acts = panel.evaluate("""() => ['not_started', 'signin'].map(state =>
        present({state, provider: 'Citi', kind: 'DOCUMENT', runnable: true, documents: 0, gaps: [], latest: []}).act)""")
    assert all(a == {"label": "Sign in", "run": "login", "primary": True} for a in acts), acts


def test_the_welcome_says_what_its_folder_holds_before_providers_are_chosen(panel):
    """The folder was checked only at Set up, two steps on. One already
    holding providers was not noticed, and one in a sync service, which
    would sync each sign-in, was not said."""
    reply = {}
    panel.route("**/api/root/check", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(reply)))

    def press(answer, typed="/Users/me/PaperPull"):
        reply.clear()
        reply.update(answer)
        return panel.evaluate("""async (typed) => {
            PROVIDERS = {providers: [], templates: true};
            if ($('newroot').value !== typed) { $('newroot').value = typed; $('newroot').oninput && $('newroot').oninput(); }
            W.step = 1; W.add = false; wShow();
            await DO['w-next']();
            return {step: W.step, said: $('rootcheck').hidden ? '' : $('rootcheck').textContent,
                    use: !$('w-useroot').hidden, next: $('w-next1').textContent};
        }""", typed)

    panel.evaluate("() => openWelcome(false).catch(() => {})")
    bad = press({"ok": False, "problem": "That is a file, not a folder. Choose a folder."})
    assert bad["step"] == 1 and bad["said"].startswith("That is a file") and not bad["use"]

    found = {"ok": True, "found": ["Chase Statements", "Amex Statements"], "found_count": 2, "synced_by": ""}
    first = press(found, "/Users/me/Old")
    assert first["step"] == 1 and first["use"]
    assert "Found 2 providers already set up here (Chase Statements, Amex Statements)." in first["said"]
    assert press(found, "/Users/me/Old")["step"] == 2, "a second Continue goes on, to add more"

    synced = {"ok": True, "found": [], "found_count": 0, "synced_by": "iCloud Drive"}
    warned = press(synced, "/Users/me/Library/Mobile Documents/PaperPull")
    assert warned["step"] == 1 and "in iCloud Drive" in warned["said"] and warned["next"] == "Continue anyway"
    assert press(synced, "/Users/me/Library/Mobile Documents/PaperPull")["step"] == 2

    assert press({"ok": True, "found": [], "found_count": 0, "synced_by": ""}, "/Users/me/New")["step"] == 2


def test_moving_says_the_pdfs_stay_unless_the_folders_are_copied(panel):
    """A history file marks every document it lists as downloaded and brings
    no PDF, so Get new never fetched them, and nothing said so. The Move card
    now leads with copying the folders, which brings everything."""
    said = panel.evaluate("""async () => {
        const was = META;
        META = null;
        placeMove(false);                   // as at start, before META is read
        const early = $('hxlead').textContent;
        META = Object.assign({}, was || {}, {apps_root: '/Users/me/PaperPull', documents_root: '/Users/me/Drive/Docs'});
        placeMove(false);
        const card = [$('hxlead').textContent, $('hxfilelead').hidden ? '' : $('hxfilelead').textContent];
        placeMove(true);
        const welcome = $('hxlead').textContent;
        await openWelcome(false).catch(() => {});
        return {early, card, welcome, aside: $('movesay').textContent};
    }""")
    assert "Export history saves a file" in said["early"]
    copy, file_ = said["card"]
    assert copy.startswith("To move everything, your PDFs included, copy your PaperPull folder, /Users/me/PaperPull")
    assert "your Documents folder, /Users/me/Drive/Docs" in copy and "choose the Documents folder again" in copy
    # Each config names the documents folder by its full path, and so do the
    # records of what was moved there, so a copy elsewhere would point at
    # the old computer's folder.
    assert "/Users/me/Drive/Docs, to the same place on the new computer, since PaperPull keeps its full path" in copy
    assert "Any folder you chose for one account's documents goes to the same place too" in copy
    assert file_.startswith("No way to copy the folders?") and "no PDF" in file_
    assert "The PDFs stay on the other computer. Copy them over, or use Restore deleted files" in said["welcome"]
    assert said["aside"].startswith("Copy your PaperPull folder from the old computer, then type where it is above")


def test_a_report_lands_on_its_file_and_where_to_send_it(panel):
    """About 15 steps from More to an attached file. The dialog said to sign
    in with no way to, the folder held several files, and the place to send
    it was under Settings, About."""
    got = panel.evaluate("""() => {
        const r = {app: 'Chase Statements', account: 'primary', provider: 'Chase', slug: 'chase', kind: 'DOCUMENT',
                   state: 'current', runnable: true, documents: 1, gaps: [], latest: [], runs: []};
        ROWS = [r];
        Object.assign(RUN, {state: 'done', app: r.app, account: r.account, provider: r.provider, kind: r.kind,
                            action: 'diagnose', scope: {year: '', start: '', end: ''}, again: false, lines: [],
                            result: null, saved: [], code: '0', refused: '', failure: false,
                            startedAt: new Date(), endedAt: new Date()});
        RUN.outcome = runOutcome();
        renderRun();
        const keep = document.querySelector('#view-run .keepopen');
        const show = keep.querySelector('[data-do="report-reveal"]');
        const link = keep.querySelector('a');
        // The dialog's own sign-in, which keeps the person, and the dialog, where they are.
        let asked = null;
        const real = startRun;
        startRun = (row, action, opts) => { asked = [row.app, action, opts]; return true; };
        DLG_ROW = r;
        DO['sp-signin']();
        startRun = real;
        return {kind: show && show.dataset.kind, text: show && show.textContent, href: link.href, target: link.target,
                rel: link.rel, asked, said: $('sp-signsay').textContent, plain: reportLink({}).match(/href="([^"]+)"/)[1]};
    }""")
    assert got["kind"] == "diagnose" and got["text"] == "Show the file"
    url = got["href"]
    assert url.startswith("https://github.com/rheeloaded/paperpull/issues/new?")
    assert "template=app-broke.yml" in url and "app=chase" in url and "title=%5BBroken%5D+chase%2C+" in url
    assert (got["target"], got["rel"]) == ("_blank", "noopener")
    assert got["asked"] == ["Chase Statements", "login", {"stay": True}]
    assert got["said"].startswith("The sign-in window is opening.")
    assert got["plain"] == "https://github.com/rheeloaded/paperpull/issues", "no slug, the issue list"


def test_every_row_carries_the_name_its_issues_use(root, monkeypatch):
    """Only a provider PaperPull ships, one providers.json names, since the
    name goes into a link to GitHub and a script named by hand could carry
    any words."""
    shipped = dict(app_module._provider_notes(), bank={"documents": "", "group": "banks"})
    monkeypatch.setattr(app_module, "_provider_notes", lambda: shipped)
    rows = _rows()
    assert rows[("Bank Statements", "primary")]["slug"] == "bank"
    assert rows[("Bank Statements", "second")]["slug"] == "bank"
    assert rows[("Shop Receipts", "primary")]["slug"] == "", "shop_receipts.py is no provider PaperPull ships"


# -- a gap a whole run could not fill (#149) ---------------------------------------
#
# A gap in the middle of a history counts toward "may have something new" on
# the home page, and Get new for all runs its account. When a whole, clean
# Run All has read the provider's list, left nothing on it to take, and the
# gap is still there, no number of such runs changes it. Such a run notes the
# gaps it left, and only those exact gaps are settled. One that appears
# afterwards, from a history put back, say, still counts.

def _gapped(newest_days_ago=5, hole=4):
    """Saved records one every 30 days with the one at `hole` missing, which
    status.py reads as a gap of one document."""
    recs = _records(newest_days_ago)
    del recs["doc-%d" % hole]
    return recs


def _clean_all(**more):
    entry = {"action": "all", "account": "primary", "started": "2026-11-06T16:00:00",
             "ended": "2026-11-06T16:01:00", "exit_code": 0, "closed": False,
             "result": {"manual_review": 0, "failed": 0, "validation_failures": 0,
                        "new_files": 0, "stopped": 0},
             "scope": [], "redownload": False, "saved": []}
    entry.update(more)
    return entry


def _listed(bank, recs, **more):
    """What a Run All leaves beside progress.json when it took all of its
    list, that list in discovery.json under the same keys, with `more` added
    to it, and the note that it was read to its end."""
    rows = {k: {"date": r["date"], "category": "Statement", "state": r["state"]}
            for k, r in recs.items()}
    (bank / "discovery.json").write_text(json.dumps(dict(rows, **more)), encoding="utf-8")
    (bank / "last-listing.json").write_text(
        json.dumps({"complete": True, "at": "2031-01-15T09:00:00"}), encoding="utf-8")


def _took_it_all(root, **more):
    """A bank whose gap a run has left, with the list that run read."""
    bank = root / "Bank Statements"
    recs = _gapped()
    (bank / "progress.json").write_text(json.dumps(recs), encoding="utf-8")
    _listed(bank, recs, **more)
    return bank


def _the_hole():
    return (date.today() - timedelta(days=5 + 30 * 4)).isoformat()


def _run_all(port, bank, account="primary"):
    out = run(port, {"app": "Bank Statements", "action": "all", "account": account})
    assert events(out, "done") == ["0"]
    return app_module._read_run_log(bank)[0]


def _gap_keys_now(bank):
    row = _rows()[("Bank Statements", "primary")]
    return app_module._gap_keys(app_module._status_module().scan_install(bank)["gaps"]), row


def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat() + "T09:00:00"


def _noted_the_day_before(bank):
    """A whole, clean run ended the day before that noted the gaps the bank
    shows now, so the next such run that notes them is the second."""
    keys = app_module._gap_keys(app_module._status_module().scan_install(bank)["gaps"])
    assert keys
    _log(bank, _clean_all(gaps_left=keys, ended=_yesterday()))


def test_a_clean_run_all_notes_the_gaps_it_left_and_settles_them(base, root):
    bank = root / "Bank Statements"
    (bank / "progress.json").write_text(json.dumps(_gapped()), encoding="utf-8")
    assert _rows()[("Bank Statements", "primary")]["state"] == "gap"
    assert _rows()[("Bank Statements", "primary")]["settled"] is False
    _listed(bank, _gapped())
    _plan(bank)
    entry = _run_all(base, bank)
    keys, row = _gap_keys_now(bank)
    assert keys and entry["gaps_left"] == keys
    # One run settles nothing, since the next may take what it could not.
    assert row["state"] == "gap" and row["settled"] is False
    # A day on, the next whole run that notes the same gaps settles them.
    log = app_module._read_run_log(bank)
    log[0]["ended"] = _yesterday()
    _log(bank, *log)
    assert _run_all(base, bank)["gaps_left"] == keys
    assert _rows()[("Bank Statements", "primary")]["settled"] is True


def _listed_no_record(bank):
    """First Horizon, Bilt, Simmons and Alpaca, whose run leaves a document
    turned off on the page with no record and finishes clean."""
    rows = json.loads((bank / "discovery.json").read_text(encoding="utf-8"))
    rows["doc-4"] = {"date": _the_hole(), "category": "Statement", "state": "Discovered"}
    (bank / "discovery.json").write_text(json.dumps(rows), encoding="utf-8")


def _a_record_saying(state):
    def leave(bank):
        _listed_no_record(bank)
        recs = json.loads((bank / "progress.json").read_text(encoding="utf-8"))
        recs["doc-4"] = {"date": _the_hole(), "state": state, "downloaded_ok": False}
        (bank / "progress.json").write_text(json.dumps(recs), encoding="utf-8")
    return leave


def _note_says(text):
    def leave(bank):
        (bank / "last-listing.json").write_text(text, encoding="utf-8")
    return leave


def _list_says(text):
    def leave(bank):
        (bank / "discovery.json").write_text(text, encoding="utf-8")
    return leave


def _gone(name):
    return lambda bank: (bank / name).unlink()


@pytest.mark.parametrize("leave", [
    _listed_no_record, _a_record_saying("Discovered"), _a_record_saying("Failed"),
    _a_record_saying("PDF Saved"), _a_record_saying("Needs Manual Review"),
    _a_record_saying("No Receipt Available"), _a_record_saying("Canceled"),
    _a_record_saying("PDF Verified"),
    _note_says('{"complete": false, "at": "2031-01-15T09:00:00"}'),
    _note_says('{"complete": "true"}'), _note_says('{"at": "2031-01-15T09:00:00"}'),
    _note_says("[true]"), _note_says("not json"), _gone("last-listing.json"),
    _list_says("{}"), _list_says("[]"), _list_says('["doc-0"]'), _list_says("not json"),
    _list_says('{"doc-0": "a row"}'), _gone("discovery.json")],
    ids=["no-record", "discovered", "failed", "pdf-saved", "set-aside", "no-control-found",
         "canceled", "pdf-verified", "list-stopped",
         "note-says-text", "note-says-nothing", "note-a-list", "note-not-json", "no-note",
         "nothing-listed", "list-empty-list", "list-a-list", "list-not-json", "row-not-a-record",
         "no-list"])
def test_a_clean_run_that_left_something_or_cannot_say_settles_nothing(base, root, leave):
    """First Horizon's real Run All listed 10, saved 9, left one for the next
    run, ended clean and settled. A run's result does not say so, so its
    records are read, and records that do not show it all count as left. A
    run the day before noted the gap, so only this one stands between."""
    bank = _took_it_all(root)
    _noted_the_day_before(bank)
    leave(bank)
    _plan(bank)
    entry = _run_all(base, bank)
    assert app_module._whole_clean_run(entry) and "gaps_left" not in entry
    row = _rows()[("Bank Statements", "primary")]
    assert row["state"] == "gap" and row["settled"] is False
    # An answer, not an error the run's note swallowed.
    assert app_module._nothing_left(bank, {}) is False


def test_records_that_will_not_read_say_nothing_was_taken(root):
    """A progress.json that is not records leaves no row to run from the
    panel, so its check is asked itself."""
    bank = _took_it_all(root)
    assert app_module._nothing_left(bank, {}) is True
    (bank / "progress.json").write_text("[]", encoding="utf-8")
    assert app_module._nothing_left(bank, {}) is False


def test_a_run_that_counts_documents_left_unsaved_settles_nothing(base, root):
    """Alpaca counts documents that share a type and a date and lists none
    of them, so its records show nothing, and its count is all there is."""
    bank = _took_it_all(root)
    _noted_the_day_before(bank)
    _plan(bank, counts={"alike": 2})
    entry = _run_all(base, bank)
    assert entry["result"]["alike"] == 2
    assert app_module._whole_clean_run(entry) and "gaps_left" not in entry
    assert _rows()[("Bank Statements", "primary")]["settled"] is False


def test_a_later_run_that_left_something_undoes_an_earlier_one(base, root):
    bank = _took_it_all(root)
    _noted_the_day_before(bank)
    _plan(bank)
    assert _run_all(base, bank)["gaps_left"]
    assert _rows()[("Bank Statements", "primary")]["settled"] is True
    _listed_no_record(bank)
    assert "gaps_left" not in _run_all(base, bank)
    assert _rows()[("Bank Statements", "primary")]["settled"] is False


@pytest.mark.parametrize("state", ["Completed", "No Longer Listed"])
def test_a_listed_document_with_nothing_to_take_is_not_left(base, root, state):
    """Each state, on a record no file was saved for. Dated as a saved
    document is, so it moves no gap. Written out here, so a state taken off
    the panel's list fails rather than takes its own case with it."""
    bank = _took_it_all(root)
    _noted_the_day_before(bank)
    recs = json.loads((bank / "progress.json").read_text(encoding="utf-8"))
    recs["extra"] = {"date": recs["doc-0"]["date"], "state": state, "downloaded_ok": False}
    (bank / "progress.json").write_text(json.dumps(recs), encoding="utf-8")
    _listed(bank, recs)
    _plan(bank)
    assert _run_all(base, bank)["gaps_left"]
    assert _rows()[("Bank Statements", "primary")]["settled"] is True


def test_a_document_saved_once_stays_taken_whatever_its_record_says_since(base, root):
    """downloaded_ok is kept for good, and a later try that failed does not
    put back what was saved."""
    bank = _took_it_all(root)
    recs = json.loads((bank / "progress.json").read_text(encoding="utf-8"))
    recs["doc-0"]["state"] = "Failed"
    (bank / "progress.json").write_text(json.dumps(recs), encoding="utf-8")
    _plan(bank)
    assert _run_all(base, bank)["gaps_left"]


def _config(bank, **settings):
    (bank / "config.json").write_text(json.dumps(dict({"output_dir": "."}, **settings)),
                                      encoding="utf-8")


@pytest.mark.parametrize("row,settings", [
    ({"category": "Statement"}, {"default_start_date": "AFTER"}),
    ({"category": "Statement", "date": ""}, {"default_start_date": "AFTER"}),
    ({"category": "Other Document"}, {"document_types": ["Statement", "Tax Document"]})],
    ids=["before-the-floor", "no-date-under-a-floor", "type-not-wanted"])
def test_a_document_the_persons_own_settings_leave_out_is_not_left(base, root, row, settings):
    """A gap the person chose to leave out may settle, as the run did not
    look there. The list of an earlier run with other settings still names
    such a document, since discovery.json never forgets."""
    after = (date.fromisoformat(_the_hole()) + timedelta(days=1)).isoformat()
    bank = _took_it_all(root, **{"doc-4": dict({"date": _the_hole(), "state": "Discovered"}, **row)})
    _noted_the_day_before(bank)
    _config(bank, **{k: after if v == "AFTER" else v for k, v in settings.items()})
    _plan(bank)
    assert _run_all(base, bank)["gaps_left"]
    assert _rows()[("Bank Statements", "primary")]["settled"] is True


@pytest.mark.parametrize("settings", [
    {}, {"default_start_date": ""}, {"default_start_date": 2031}, {"default_start_date": "2000-01-01"},
    {"document_types": []}, {"document_types": "Statement"}, {"document_types": ["Tax Document", "Statement"]}])
def test_settings_that_do_not_leave_a_document_out_leave_it_left(base, root, settings):
    """A setting that does not plainly leave it out, or one the config file
    does not hold, which the app's own defaults may answer otherwise."""
    bank = _took_it_all(root, **{"doc-4": {"date": _the_hole(), "category": "Tax Document",
                                           "state": "Discovered"}})
    _config(bank, **settings)
    _plan(bank)
    assert "gaps_left" not in _run_all(base, bank)
    # An answer, not an error the run's note swallowed.
    assert app_module._nothing_left(bank, settings) is False


def test_a_config_that_will_not_read_leaves_nothing_out(base, root):
    bank = _took_it_all(root, **{"doc-4": {"date": _the_hole(), "category": "Statement",
                                           "state": "Discovered"}})
    meta = {"script_name": "bank_docs.py", "dir": str(bank)}
    for text in ("not json", "[]"):
        (bank / "config.json").write_text(text, encoding="utf-8")
        assert app_module._took_everything(meta, "primary", bank, {}) is False


def test_a_second_person_is_held_to_their_own_settings(base, root):
    """The first person's floor says nothing of what the second person's
    run left."""
    bank = root / "Bank Statements"
    second = root / "Bank Statements - second"
    recs = _gapped()
    (second / "progress.json").write_text(json.dumps(recs), encoding="utf-8")
    _listed(second, recs, **{"doc-4": {"date": _the_hole(), "category": "Statement",
                                       "state": "Discovered"}})
    floor = (date.fromisoformat(_the_hole()) + timedelta(days=1)).isoformat()
    _config(bank, default_start_date=floor)
    _plan(bank)
    assert "gaps_left" not in _run_all(base, second, account="second")
    _config(bank)
    (bank / "config.second.json").write_text(
        json.dumps({"output_dir": "../Bank Statements - second", "default_start_date": floor}),
        encoding="utf-8")
    assert _run_all(base, second, account="second")["gaps_left"]


def test_a_gap_that_appears_after_the_run_is_not_settled(root):
    bank = root / "Bank Statements"
    (bank / "progress.json").write_text(json.dumps(_gapped()), encoding="utf-8")
    _log(bank, _clean_all(gaps_left=[]))
    row = _rows()[("Bank Statements", "primary")]
    assert row["state"] == "gap" and row["settled"] is False


@pytest.mark.parametrize("change", [
    {"action": "pilot"}, {"action": "resume"}, {"scope": ["--year", "2026"]},
    {"redownload": True}, {"exit_code": 1}, {"closed": True},
    {"result": {"stopped": 1}}, {"result": {"list_not_read": 1}},
    {"result": {"failed": 2}}, {"gaps_left": None}])
def test_only_a_whole_clean_run_all_settles_a_gap(root, change):
    """A pilot takes only the newest few, a scoped run reads part of the
    history, and a run that stopped, failed or was closed may not have read
    the list at all, so none of them says a gap cannot be filled."""
    bank = root / "Bank Statements"
    (bank / "progress.json").write_text(json.dumps(_gapped()), encoding="utf-8")
    keys, _row = _gap_keys_now(bank)
    entry = _clean_all(**dict({"gaps_left": keys}, **change))
    assert app_module._whole_clean_run(entry) is (change == {"gaps_left": None})
    _log(bank, entry)
    # A run that failed, stopped or was closed leaves the row stopped, which
    # comes first, and every other leaves it a gap. Neither is settled.
    assert _rows()[("Bank Statements", "primary")]["settled"] is False


def test_the_newest_whole_run_is_the_one_that_settles(root):
    """Older whole runs that left the gap do not settle it once a newer
    whole run has noted different gaps."""
    bank = root / "Bank Statements"
    (bank / "progress.json").write_text(json.dumps(_gapped()), encoding="utf-8")
    keys, _row = _gap_keys_now(bank)
    before = _clean_all(gaps_left=keys, ended="2026-11-05T09:00:00")
    _log(bank, _clean_all(gaps_left=[]), _clean_all(gaps_left=keys), before)
    assert _rows()[("Bank Statements", "primary")]["settled"] is False
    _log(bank, _clean_all(gaps_left=keys), _clean_all(gaps_left=[]), before)
    assert _rows()[("Bank Statements", "primary")]["settled"] is True


def test_only_a_gap_row_is_ever_settled(root):
    """An account that is due, or whose run stopped, keeps its place in the
    queue whatever gaps a run left, since a new document may be waiting."""
    bank = root / "Bank Statements"
    (bank / "progress.json").write_text(json.dumps(_gapped(newest_days_ago=45)), encoding="utf-8")
    keys, row = _gap_keys_now(bank)
    _log(bank, _clean_all(gaps_left=keys), _clean_all(gaps_left=keys, ended="2026-11-05T09:00:00"))
    row = _rows()[("Bank Statements", "primary")]
    assert row["state"] in ("due", "overdue") and row["settled"] is False
    (bank / "progress.json").write_text(json.dumps(_gapped()), encoding="utf-8")
    _log(bank, {"action": "all", "exit_code": 1, "ended": "2026-11-06T17:00:00",
                "result": {"stopped": 1}}, _clean_all(gaps_left=keys),
         _clean_all(gaps_left=keys, ended="2026-11-05T09:00:00"))
    row = _rows()[("Bank Statements", "primary")]
    assert row["state"] == "stopped" and row["settled"] is False


def test_two_series_never_share_a_gap_key():
    """An account "A|B" with summary "C" and an account "A" with summary
    "B|C", on the same dates, are two series and two keys."""
    one = {"account": "A|B", "summary": "C", "after": date(2020, 1, 31), "before": date(2020, 3, 31)}
    two = dict(one, account="A", summary="B|C")
    assert len(app_module._gap_keys([one, two])) == 2
    assert app_module._gap_keys([one]) != app_module._gap_keys([two])


def test_the_home_queue_leaves_out_a_settled_row():
    js = (Path(app_module.__file__).resolve().parent / "static" / "app.js").read_text(encoding="utf-8")
    start = js.index("function queueTargets()")
    body = js[start:js.index("\n}\n", start)]
    assert "!r.settled" in body


# -- what the panel reads of every app, held to the apps ------------------------------

REPO = Path(app_module.__file__).resolve().parents[1]


@functools.lru_cache(maxsize=None)
def _document_apps():
    """Each app that files documents, with its own modules parsed. Only
    these have gaps (status.find_gaps)."""
    apps = {}
    for spec in sorted((REPO / "apps").glob("*/storage.py")):
        if re.search(r"kind\s*=\s*RECEIPT", spec.read_text(encoding="utf-8")):
            continue
        trees = [ast.parse(py.read_text(encoding="utf-8")) for py in spec.parent.glob("*.py")
                 if py.name != "storage.py"]
        apps[spec.parent.name] = trees
    assert len(apps) > 60
    return apps


def _unparsed(trees, name):
    return "\n".join(ast.unparse(node) for tree in trees for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == name)


def test_every_app_keeps_what_it_lists_and_what_it_took_under_one_key():
    """The panel reads a document as left when discovery.json names it and
    progress.json holds no record of it taken under that key. That is true
    only while each app takes its run from discovery.json, asks progress.json
    by the key and writes it there, and calls done at least what the panel
    calls nothing left to take. An app this fails for reads as left on every
    run or, the other way, as taken when it is not."""
    for name, trees in _document_apps().items():
        done = _unparsed(trees, "_already_done")
        assert "self.progress.get(doc.key)" in done, name
        for state in ("COMPLETED", "PDF_VERIFIED", "NO_RECEIPT_AVAILABLE", "CANCELED"):
            assert "State.%s.value" % state in done, (name, state)
        assert "self.progress.update(doc.key, rec)" in _unparsed(trees, "_record"), name
        assert "self.discovery.data.values()" in _unparsed(trees, "_select"), name


def test_every_app_leaves_out_by_the_settings_the_panel_reads():
    """_settings_leave_out says what each app's _in_scope does with a Run All
    with no dates. Were an app to take what the panel reads as left out by
    the person's settings, a document it left would read as their choice."""
    for name, trees in _document_apps().items():
        scope = _unparsed(trees, "_in_scope")
        assert "if not doc_types.wanted(doc.category, self.config):" in scope, name
        dates = scope + _unparsed(trees, "_in_dates")
        assert "self.config.get('default_start_date')" in dates, name
        assert ("if floor and (not doc.date or doc.date < floor):" in dates
                or "if floor and (not day or day < floor):" in dates), name


# What an app's log says of a document it saw and did not list.
_SAYS_LEFT_OUT = re.compile(
    r"left out|left alone|left for a person|waits for the next run|no usable|skipped|skipping", re.I)
# What the same words say of something else, a run's scope, a check, a tab,
# a page's pager, what a bill's own file is drawn with, a render that is
# counted as a failure, and First Horizon's panel, whose list then stops.
_SOMETHING_ELSE = re.compile(r"outside the run's scope|identity check|a tab opened|stylesheet|"
                             r"pagination control|an earlier bill|the PDF render|panel title")


def _says_it_left_a_document_out(trees):
    for tree in trees:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "log"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                said = node.args[0].value
                if _SAYS_LEFT_OUT.search(said) and not _SOMETHING_ELSE.search(said):
                    return True
    return False


def test_every_app_whose_list_says_it_left_a_document_out_settles_no_gap():
    """What such a list leaves out is in no record, so the panel cannot see
    it, and a run of that app has to settle nothing. An app that starts to
    say so in a log line written as one string joins _LISTS_LEAVE_OUT. One
    that says it in other words, in an f-string or a print, or drops a row
    and says nothing, cannot be found here or by the panel. The second run on
    another day that _settled waits for is there for those."""
    said = {name for name, trees in _document_apps().items() if _says_it_left_a_document_out(trees)}
    assert said == set(app_module._LISTS_LEAVE_OUT)


@pytest.mark.parametrize("slug", sorted(app_module._LISTS_LEAVE_OUT))
def test_a_list_that_can_leave_a_document_out_settles_nothing(root, slug):
    bank = _took_it_all(root)
    assert app_module._took_everything(
        {"script_name": "bank_docs.py", "dir": str(bank)}, "primary", bank, {}) is True
    assert app_module._took_everything(
        {"script_name": slug + "_docs.py", "dir": str(bank)}, "primary", bank, {}) is False


def test_a_run_of_such_an_app_notes_no_gaps(base, root):
    bank = _took_it_all(root)
    (bank / "bank_docs.py").rename(bank / "wellsfargo_docs.py")
    _plan(bank)
    entry = _run_all(base, bank)
    assert app_module._whole_clean_run(entry) and "gaps_left" not in entry


# -- two whole runs on two days ------------------------------------------------------

def _two_gaps():
    gaps = [{"account": "", "summary": "Bank Statement", "after": date(2031, 1, 31),
             "before": date(2031, 3, 31)},
            {"account": "", "summary": "Bank Statement", "after": date(2031, 5, 31),
             "before": date(2031, 7, 31)}]
    one, two = app_module._gap_keys(gaps)
    return gaps, one, two


def _on(day, keys, at="09:00:00", **more):
    return _clean_all(gaps_left=list(keys), ended="%sT%s" % (day, at), **more)


def test_a_gap_settles_once_two_whole_runs_on_two_days_noted_it():
    """A statement not ready yet, or a year that did not answer, leaves no
    trace in some apps' records, and the next run usually takes it. So one
    run settles nothing, nor do two on one day."""
    gaps, one, two = _two_gaps()
    both = [one, two]
    settled = app_module._settled
    assert settled("gap", gaps, [_on("2031-02-15", both)]) is False
    assert settled("gap", gaps, [_on("2031-02-15", both, "17:00:00"), _on("2031-02-15", both)]) is False
    assert settled("gap", gaps, [_on("2031-02-15", both), _on("2031-02-14", both)]) is True
    # A run that is not whole between them changes nothing.
    pilot = _on("2031-02-16", [], action="pilot")
    assert settled("gap", gaps, [pilot, _on("2031-02-15", both), _on("2031-02-14", both)]) is True


def test_every_gap_has_to_be_noted_by_both_runs():
    """A run that noted one gap of two says nothing of the other."""
    gaps, one, two = _two_gaps()
    settled = app_module._settled
    assert settled("gap", gaps, [_on("2031-02-15", [one]), _on("2031-02-14", [one, two])]) is False
    assert settled("gap", gaps, [_on("2031-02-15", [one, two]), _on("2031-02-14", [one])]) is False
    # Each gap noted on another day, by an earlier run of its own.
    assert settled("gap", gaps, [_on("2031-02-15", [one, two]), _on("2031-02-14", [one]),
                                 _on("2031-02-13", [two])]) is True


def test_the_newest_whole_run_has_to_be_one_that_noted_the_gap():
    """Two earlier runs that noted it do not settle it once a newer whole run
    left something, and so noted nothing."""
    gaps, one, two = _two_gaps()
    both = [one, two]
    log = [_on("2031-02-16", []), _on("2031-02-15", both), _on("2031-02-14", both)]
    assert app_module._settled("gap", gaps, log) is False
    del log[0]["gaps_left"]
    assert app_module._settled("gap", gaps, log) is False


@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("ended", ["", "yesterday", None])
def test_a_run_whose_day_is_not_known_counts_for_nothing(which, ended):
    gaps, one, two = _two_gaps()
    log = [_on("2031-02-15", [one, two]), _on("2031-02-14", [one, two])]
    log[which]["ended"] = ended
    assert app_module._settled("gap", gaps, log) is False


# Every state a document app writes on a record, judged. Completed is a
# document taken and No Longer Listed one its provider's whole list stopped
# showing. The rest leave something to take.
_TAKEN_OR_GONE = {"COMPLETED": "Completed", "NO_LONGER_LISTED": "No Longer Listed"}
_LEFT_TO_TAKE = {"DISCOVERED", "PDF_SAVED", "FAILED", "NEEDS_MANUAL_REVIEW", "NO_RECEIPT_AVAILABLE"}


def _states_written(trees):
    """Each State an app writes, as a call's argument, a state= keyword, or
    a "state" key of a dict."""
    found = set()
    for tree in trees:
        for node in ast.walk(tree):
            values = []
            if isinstance(node, ast.Call):
                values += list(node.args) + [k.value for k in node.keywords if k.arg == "state"]
            elif isinstance(node, ast.Dict):
                values += [v for k, v in zip(node.keys, node.values)
                           if isinstance(k, ast.Constant) and k.value == "state"]
            for v in values:
                if isinstance(v, ast.Attribute) and v.attr == "value":
                    v = v.value
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id == "State":
                    found.add(v.attr)
    return found


def test_every_state_an_app_writes_is_judged_taken_or_left():
    """No Receipt Available is Wealthfront's download control not found and
    Dominion's placeholder for a bill with no PDF, so a run that did not fill
    the gap may have been refused it. A state an app starts to write has to
    be judged here before it can count as nothing left."""
    written = set().union(*(_states_written(trees) for trees in _document_apps().values()))
    assert written <= set(_TAKEN_OR_GONE) | _LEFT_TO_TAKE, written
    assert set(_TAKEN_OR_GONE) <= written
    assert set(app_module._NOTHING_TO_TAKE) == set(_TAKEN_OR_GONE.values())
