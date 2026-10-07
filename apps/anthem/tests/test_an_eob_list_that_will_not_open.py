"""A run whose EOB list would not open stops, after whatever else it reads.

Discover asks whether the person's tab is on Anthem's member site and
signed in, asks again after a session check, and when the answer was still
no it printed a line and returned. Run All then read the member documents, ID cards and letters and
finished clean, and so did Pilot, with no EOB listed, so the panel called a
run that never read the EOB list finished. Now the run stops. Run All still
reads the other three lists first, since each is a list of its own and a
plain stop at the EOBs would drop them, and stops at its end. Pilot,
Discover and a dry run, which read nothing else, stop at once.

Driven through the app's own main with no console. The browser is a
stand-in that answers whatever it is asked, the EOB center's opener and the
session check are replaced, and the three other lists are counted rather
than read, so nothing here reaches Anthem.
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
from paperpull_core.run_reporting import PREFIX

OTHER_LISTS = ("cmd_documents", "cmd_id_cards", "cmd_letters")


class Context:
    """A signed-in context with no tab of the person's, so the run opens
    one of its own, which answers whatever it is asked."""

    def __init__(self):
        self.pages = []

    def new_page(self):
        tab = MagicMock(name="tab")
        tab.url = "about:blank"
        tab.is_closed.return_value = False
        self.pages.append(tab)
        return tab

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MagicMock(name="context.%s" % name)


class Playwright:
    def __init__(self):
        browser = MagicMock(name="browser")
        browser.contexts = [Context()]
        self.chromium = SimpleNamespace(connect_over_cdp=lambda *_a, **_kw: browser)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """main with these arguments, the EOB center opening or not. Gives what
    it printed with its lines joined, the result line the panel reads, how
    it ended, and the order things happened in."""
    config = json.loads((Path(app_mod.__file__).parent / "config.example.json")
                        .read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"),
                   "cdp_url": "http://127.0.0.1:9", "delay_min_seconds": 0,
                   "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api
    monkeypatch.setattr(sync_api, "sync_playwright", Playwright())
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    def no_console(*_a, **_kw):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_console)
    monkeypatch.setattr(app_mod.App, "check_session", lambda *_a, **_kw: False)
    monkeypatch.setattr(site, "collect_documents", lambda _page: [])
    happened = []
    for name in OTHER_LISTS:
        monkeypatch.setattr(app_mod.App, name,
                            lambda _app, _name=name: happened.append(_name))
    process = app_mod.App.process

    def handed(app, docs, *a, **kw):
        happened.append("process")
        return process(app, docs, *a, **kw)
    monkeypatch.setattr(app_mod.App, "process", handed)

    def go(*args, opens=False):
        happened.clear()
        monkeypatch.setattr(site, "ensure_statements", lambda _page: opens)
        capsys.readouterr()
        try:
            ended = ("returned", app_mod.main(["--config", str(cfg), *args]))
        except SystemExit as e:
            ended = ("exit", e.code)
        out = capsys.readouterr().out
        results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
                   if line.startswith(PREFIX)]
        return " ".join(out.split()), (results[-1] if results else None), ended, list(happened)
    return go


NOT_LISTED = "Your EOBs were not listed, so this run stops here"


def test_run_all_reads_the_other_lists_and_then_stops(run):
    said, result, ended, happened = run("--all", "--yes")
    assert happened == ["process", *OTHER_LISTS], happened
    assert ended == ("exit", 0) and result["stopped"] == 1, said
    assert said.index("Could not open your Anthem statements") < said.index(NOT_LISTED)


@pytest.mark.parametrize("args", [("--pilot",), ("--all", "--yes", "--dry-run"),
                                  ("--dry-run",)],
                         ids=["pilot", "run all in a dry run", "dry run"])
def test_a_run_that_reads_no_other_list_stops_at_once(run, args):
    said, result, ended, happened = run(*args)
    assert happened == [], happened
    assert ended == ("exit", 0) and result["stopped"] == 1, said
    assert NOT_LISTED in said


def test_discover_alone_stops(run):
    said, _result, ended, happened = run("--discover")
    assert ended == ("exit", 0) and happened == [], said
    assert NOT_LISTED in said


def test_run_all_whose_eob_list_opens_still_finishes_clean(run):
    """The other side, so the stop is the EOB list's and nothing else's.
    An EOB center that opens with no EOB in it is a list read whole."""
    said, result, ended, happened = run("--all", "--yes", opens=True)
    assert happened == ["process", *OTHER_LISTS], happened
    assert ended == ("returned", 0) and result["stopped"] == 0, said
    assert NOT_LISTED not in said
