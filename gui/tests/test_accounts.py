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
import asyncio
import http.client
import json
import os
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
    assert ", 23 new files</span>" in panel.evaluate("(e) => runLine(e)", entry)
    o = _outcome(panel, _counted(new_files=23, failed=1), saved, action)
    assert o["title"] == "23 new documents saved, some need a look"


def test_a_run_that_saved_nothing_still_says_so(panel):
    o = _outcome(panel, _counted(), [])
    assert (o["tone"], o["title"]) == ("ok", "Nothing new")
    assert _outcome(panel, _counted(failed=1), [])["title"] == "Finished, needs attention"
    # A log in the run's folder can hold anything, and an odd count in it
    # is no count.
    for odd in ("23", -1, 2.5, None, [3]):
        entry = {"action": "all", "exit_code": 0, "result": {"new_files": odd}, "saved": []}
        assert ", nothing new</span>" in panel.evaluate("(e) => runLine(e)", entry), odd
    entry = {"action": "all", "exit_code": 0, "result": {}, "saved": ["a.pdf", "b.pdf"]}
    assert ", 2 new files</span>" in panel.evaluate("(e) => runLine(e)", entry)


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
        with urllib.request.urlopen(req, timeout=60) as r:
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
