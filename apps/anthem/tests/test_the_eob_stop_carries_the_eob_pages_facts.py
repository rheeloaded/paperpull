"""The failure file of Run All's EOB stop describes the page where the EOB
list would not open (threads of 2026-11-16, item 5).

Run All with an EOB list that would not open goes on to read the member
documents, ID cards, letters and claims summaries, and writes its failure
file where it stops, at its end, so the run's one file goes to a later
failure if there is one (#228). That file's step and reason named the EOB
refusal, while its page and selectors sections were read at the stop and
described whatever the last list left in the tab.

Now Run All reads the page once at the refusal, the same two reads a
failure file makes, and adds a checkpoint there, and the EOB stop's file
carries those, with one fact that says so. Discover, Pilot and the dry
runs, which stop at the refusal, are as before.

Driven through the app's own main with no console. The tab is a stand-in
whose page answers differ at each step, so a file can only carry the
refusal's answers if they were taken there. Every name, number and page
text is invented, and the page carries a canary that must never come out.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import anthem_docs as app_mod
import anthem_site as site
from paperpull_core import failure, journal
from paperpull_core.run_reporting import PREFIX

OTHER_LISTS = ("cmd_documents", "cmd_id_cards", "cmd_letters", "cmd_claims_summaries")
CANARY = "CANARY-7Q3 Dana Example 4111 Elm Lane"
CANARY_CLASS = "canary-7q3-member"
REFUSAL_FACT = "page_read_where_eob_list_would_not_open"
REFUSAL_CHECKPOINT = "where the eob list would not open"


class Tab:
    """The run's tab. Its page answers by `at`, which the run's steps move."""

    def __init__(self, shared):
        self.shared = shared
        self.url = "https://member.example.invalid/?who=" + CANARY.replace(" ", "+")
        self.closed = False

    def is_closed(self):
        return self.closed

    def evaluate(self, script, *args):
        if self.closed:
            raise RuntimeError("Target page, context or browser has been closed")
        at = self.shared["at"]
        if at in self.shared.get("unreadable", ()):
            raise RuntimeError("Execution context was destroyed")
        node = {"tag": "div", "cls": CANARY_CLASS, "text": CANARY, "w": 10, "h": 10}
        if script == failure._PAGE_STATE_JS:
            self.shared["state_reads"].append(at)
            return {"ready": "complete", "body_text_len": at, "visible_elements": at // 100,
                    "body_scroll_height": at, "counts": {}, "largest_visible": node}
        if script == failure._CENSUS_JS:
            return [{"matched": at // 1111, "visible": 1, "nodes": [node]} for _ in args[0]]
        if script == journal._WATCH_JS:
            return {}
        return 0

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name="tab.%s" % name)


class Context:
    def __init__(self, shared):
        self.shared = shared
        self.pages = []

    def new_page(self):
        tab = Tab(self.shared)
        self.pages.append(tab)
        self.shared["tabs"].append(tab)
        return tab

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name="context.%s" % name)


class Playwright:
    def __init__(self, shared):
        browser = MagicMock(name="browser")
        browser.contexts = [Context(shared)]
        self.chromium = SimpleNamespace(connect_over_cdp=lambda *_a, **_kw: browser)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    config = json.loads((Path(app_mod.__file__).parent / "config.example.json")
                        .read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"),
                   "cdp_url": "http://127.0.0.1:9", "delay_min_seconds": 0,
                   "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    shared = {"at": 9999, "state_reads": [], "tabs": [], "asked": 0, "apps": []}
    import playwright.sync_api as sync_api
    monkeypatch.setattr(sync_api, "sync_playwright", Playwright(shared))
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    def no_console(*_a, **_kw):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_console)
    monkeypatch.setattr(site, "collect_documents", lambda _page: [])
    # Anthem declares no selectors of its own. One is given here, so the
    # selectors section has something to say at each step.
    monkeypatch.setattr(site, "FALLBACK", {"eob_row": "tr.eob-row"}, raising=False)
    happened = []

    def documents(app):
        happened.append("cmd_documents")
        app.journal.checkpoint("read the member documents")
        shared["at"] = 3333
    monkeypatch.setattr(app_mod.App, "cmd_documents", documents)
    for name in OTHER_LISTS[1:]:
        monkeypatch.setattr(app_mod.App, name, lambda _app, _name=name: happened.append(_name))
    stop = app_mod.App._stop_if_eobs_unread

    def stopping(app):
        shared["apps"].append(app)
        if shared["at"] == 3333:
            shared["at"] = 4444
        return stop(app)
    monkeypatch.setattr(app_mod.App, "_stop_if_eobs_unread", stopping)

    def go(*args, opens=False, check_moves=False):
        happened.clear()
        shared.update(at=9999, asked=0)
        shared["state_reads"].clear()

        def ensure(_page):
            shared["asked"] += 1
            if shared["asked"] == 2 and not check_moves:
                shared["at"] = 1111
            return opens

        def check(*_a, **_kw):
            if check_moves:
                shared["at"] = 2222
            return False
        monkeypatch.setattr(site, "ensure_statements", ensure)
        monkeypatch.setattr(app_mod.App, "check_session", check)
        capsys.readouterr()
        try:
            ended = ("returned", app_mod.main(["--config", str(cfg), *args]))
        except SystemExit as e:
            ended = ("exit", e.code)
        out = capsys.readouterr().out
        results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
                   if line.startswith(PREFIX)]
        return " ".join(out.split()), (results[-1] if results else None), ended, list(happened)
    go.shared = shared
    go.out = tmp_path / "out"
    return go


def failure_files(run) -> list:
    return sorted((run.out / "Diagnostics").glob("failure-*.json"))


def the_file(run) -> dict:
    found = failure_files(run)
    assert len(found) == 1, found
    text = found[0].read_text(encoding="utf-8")
    assert "CANARY" not in text and "Dana Example" not in text and "Elm Lane" not in text
    assert CANARY_CLASS not in text
    return json.loads(text)


def matched(report) -> set:
    return {e.get("matched") for e in report.get("selectors") or [] if "matched" in e}


def checkpoints(report) -> list:
    return [e.get("name") for e in report["journal"]["entries"] if e.get("kind") == "checkpoint"]


def test_run_all_writes_the_page_as_it_was_where_the_eob_list_would_not_open(run):
    """Y1.1 and Y3.1."""
    said, result, ended, happened = run("--all", "--yes")
    assert happened == list(OTHER_LISTS), happened
    assert ended == ("exit", 0) and result["stopped"] == 1, said
    report = the_file(run)
    assert (report["step"], report["reason"]) == ("open the eob list",
                                                  "the eob list would not open")
    assert report["page"]["body_text_len"] == 1111, report["page"]
    assert matched(report) == {1}, report["selectors"]
    assert report["extra"] == {REFUSAL_FACT: True}, report.get("extra")
    assert said.index("Could not open your Anthem statements") \
        < said.index("This run wrote a file about what went wrong") \
        < said.index("Your EOBs were not listed"), said
    assert "CANARY" not in said and CANARY_CLASS not in said


def test_the_journal_has_the_refusal_first_and_the_stop_last(run):
    """Y1.2."""
    run("--all", "--yes")
    names = checkpoints(the_file(run))
    assert REFUSAL_CHECKPOINT in names, names
    assert names.index(REFUSAL_CHECKPOINT) < names.index("read the member documents"), names
    assert names[-1] == "when the run gave up", names


def test_a_later_failure_keeps_its_own_page(run, monkeypatch):
    """Y1.3. The one file of the run is the later one's, read live."""
    def claims(app):
        run.shared["at"] = 4444
        app.write_failure("read the claims summaries", "a claims summary was not read")
    monkeypatch.setattr(app_mod.App, "cmd_claims_summaries", claims)
    said, result, ended, _happened = run("--all", "--yes")
    assert ended == ("exit", 0) and result["stopped"] == 1, said
    report = the_file(run)
    assert report["step"] == "read the claims summaries"
    assert report["page"]["body_text_len"] == 4444, report["page"]
    assert REFUSAL_FACT not in (report.get("extra") or {})
    assert run.shared["apps"][-1]._eob_page_facts is None


@pytest.mark.parametrize("args", [("--discover",), ("--pilot",), ("--all", "--yes", "--dry-run"),
                                  ("--dry-run",)],
                         ids=["discover", "pilot", "run all in a dry run", "dry run"])
def test_a_run_that_stops_at_the_refusal_reads_the_page_once_as_before(run, args):
    """Y1.4 and Changes item 13. No snapshot, no checkpoint, no fact."""
    said, _result, ended, happened = run(*args)
    assert ended == ("exit", 0) and happened == [], said
    report = the_file(run)
    assert report["page"]["body_text_len"] == 1111
    assert run.shared["state_reads"] == [1111], run.shared["state_reads"]
    assert REFUSAL_CHECKPOINT not in checkpoints(report)
    assert REFUSAL_FACT not in (report.get("extra") or {})


def test_an_eob_list_that_opens_takes_no_snapshot(run):
    """Y1.5, the control."""
    said, result, ended, _happened = run("--all", "--yes", opens=True)
    assert ended == ("returned", 0) and result["stopped"] == 0, said
    assert run.shared["state_reads"] == [] and not failure_files(run)


def test_the_page_is_read_after_the_session_check(run):
    """Y2.1. A session check that moves the tab comes before the read."""
    run("--all", "--yes", check_moves=True)
    assert the_file(run)["page"]["body_text_len"] == 2222


def test_a_tab_closed_by_the_stop_still_gives_the_refusals_page(run, monkeypatch):
    """Y2.3."""
    def claims(app):
        run.shared["tabs"][0].closed = True
    monkeypatch.setattr(app_mod.App, "cmd_claims_summaries", claims)
    said, result, ended, _happened = run("--all", "--yes")
    assert ended == ("exit", 0) and result["stopped"] == 1, said
    assert the_file(run)["page"]["body_text_len"] == 1111


def test_a_page_that_cannot_be_read_at_the_refusal(run):
    """Y2.4 and Changes item 12. The run ends as before, and the file says
    the read failed, never what the tab shows at the stop."""
    run.shared["unreadable"] = (1111,)
    try:
        said, result, ended, happened = run("--all", "--yes")
    finally:
        run.shared["unreadable"] = ()
    assert happened == list(OTHER_LISTS) and ended == ("exit", 0) and result["stopped"] == 1, said
    report = the_file(run)
    assert "evaluation" in report["page"] and "body_text_len" not in report["page"], report["page"]
    assert report["extra"] == {REFUSAL_FACT: True}


def test_the_snapshot_is_used_once(run):
    """Y2.6. Cleared after the stop's file, so a later file reads the page."""
    run("--all", "--yes")
    app = run.shared["apps"][-1]
    assert app._eob_page_facts is None
    app.stats.pop("failure_files", None)
    app._work_page = run.shared["tabs"][0]
    run.shared["at"] = 5555
    app.write_failure("a later step", "a later reason")
    later = [json.loads(f.read_text(encoding="utf-8")) for f in failure_files(run)]
    assert any(r.get("step") == "a later step" and r["page"]["body_text_len"] == 5555
               for r in later), later


def test_ctrl_c_after_the_refusal_writes_nothing(run, monkeypatch):
    """Y2.8. The snapshot is in memory only."""
    def interrupted(app):
        raise KeyboardInterrupt
    monkeypatch.setattr(app_mod.App, "cmd_documents", interrupted)
    said, _result, ended, _happened = run("--all", "--yes")
    assert ended == ("returned", 130), said
    assert not failure_files(run)
    for f in run.out.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".txt", ".log", ".csv"):
            text = f.read_text(encoding="utf-8", errors="replace")
            assert "1111" not in text and REFUSAL_FACT not in text, f.name
