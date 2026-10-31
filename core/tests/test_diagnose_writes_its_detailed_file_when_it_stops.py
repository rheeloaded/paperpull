"""Diagnose writes its detailed file even when a stop interrupts its look.

pressing.Stop subclasses SystemExit, so an app's `except Exception` in
cmd_diagnose never caught one. A stop out of goto_documents, or out of a
later step that presses, left cmd_diagnose before it wrote
diagnose-documents.json, the detailed file a repair is made from, and only
the safe survey pressing.stop_run writes was left (#27). Wells Fargo's
Diagnose catches the stop, surveys the page the window shows without
following any link, and writes its file saying it could not open the
documents page and why.

Each app that stops through pressing.stop_run is run here with a made-up
config, no browser and a page that holds nothing. Every site call its
Diagnose makes on the page is replaced by one that answers as an empty page
would, and one of them stops. The detailed file has to be there with the
stop's step and reason, the stop's own words said, and, when the documents
page is what would not open, nothing past it pressed and no link followed.
Every word here is made up.
"""
import ast
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import pressing

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")) and entry_of(d)
              and "pressing.stop_run(app, " in entry_of(d).read_text(encoding="utf-8"))

# The ones a stop could reach, every one named, so a census that found
# fewer is not mistaken for one that passed.
NAMED_GOTO = {"alpaca", "bilt", "chasebusiness", "firsthorizon", "irs", "sdge", "shelbycounty",
              "simmons", "spectrum", "venmo", "coinbase", "nelnet", "optum", "wellsfargo",
              "adp", "amfam", "applecard", "att", "etrade", "golden1", "newrez", "sba", "smud",
              "statefarm", "treasurydirect", "pge"}
NAMED_STEPS = {("bestbuy", "capture_history_query"), ("bestbuy", "year_choices"),
               ("bestbuy", "cmd_discover"), ("coinbase", "shown_documents"),
               ("mtb", "collect_statement_rows"), ("nelnet", "collect_download_docs"),
               ("optum", "collect_download_docs"), ("wellsfargo", "collect_download_docs"),
               ("pge", "collect_download_docs"), ("applecard", "goto_section"),
               ("meijer", "goto_orders"), ("meijer", "open_tab"),
               ("meijer", "collect_cards")}

# Steps only a row on the page reaches, which a page that holds nothing
# never shows. A stop out of one is caught around the same look as the
# steps before it.
PAST_A_ROW = {("meijer", "row_controls"), ("meijer", "survey_receipt")}

# Steps that press or move the page. None is made once the documents page
# would not open.
PRESSING_STEPS = {"expand_all", "scroll_full_page", "collect_download_docs", "shown_documents",
                  "year_choices", "capture_history_query", "collect_statement_rows"}

GOTO_STOP = pressing.Stop(
    "open the statements page", "the page has no statements and documents link",
    ["The run could not open the statements page from the page the window shows."],
    {"hidden": 2})
STEP_STOP = pressing.Covered(
    "choose a year", "something on the page is over the control",
    ["Something on the page is over the year menu, so it was not pressed."],
    {"hidden": 1}, after_a_press=True)


def diagnose_of(app: Path) -> ast.FunctionDef:
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    (fn,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "cmd_diagnose"]
    return fn


def page_calls(app: Path) -> list:
    """The site functions Diagnose's look calls with the page, in the try
    statements of cmd_diagnose's own body, in the order they appear. A try
    inside a loop, Best Buy's over a purchase of each kind, is left out,
    since an empty page gives it nothing to go round."""
    names = []
    for stmt in diagnose_of(app).body:
        if not isinstance(stmt, ast.Try):
            continue
        for part in stmt.body:
            for n in ast.walk(part):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "site" \
                        and any(isinstance(a, ast.Name) and a.id == "page" for a in n.args) \
                        and n.func.attr not in names:
                    names.append(n.func.attr)
    return names


def discovers(app: Path) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "cmd_discover"
               for n in ast.walk(diagnose_of(app)))


def cases():
    goto, steps = [], []
    for app in APPS:
        calls = page_calls(app)
        if "goto_documents" in calls:
            goto.append(app)
        for name in calls:
            if name != "goto_documents" and (app.name, name) not in PAST_A_ROW:
                steps.append((app, name))
        if discovers(app):
            steps.append((app, "cmd_discover"))
    return goto, steps


GOTO_APPS, STEPS = cases()


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


class EmptyLocator:
    def count(self):
        return 0

    def nth(self, _i):
        return self

    @property
    def first(self):
        return self


class EmptyPage:
    """A page that holds nothing. Every read of it answers as an empty
    page would, and nothing on it can be pressed."""
    url = "about:blank"

    def title(self):
        return ""

    def locator(self, *_a, **_k):
        return EmptyLocator()

    get_by_role = locator

    def screenshot(self, *_a, **_k):
        return b""

    def evaluate(self, *_a, **_k):
        return None

    def wait_for_timeout(self, *_a, **_k):
        return None

    def is_closed(self):
        return False

    # Meijer listens for the page's JSON answers, and none come.
    def on(self, *_a, **_k):
        return None

    remove_listener = on


def empty_answer(name: str):
    """What a site call answers on a page that holds nothing."""
    if name.startswith(("goto_", "open_")):
        return True
    if name.startswith(("collect_", "find_", "shown_", "row_")) or name in ("year_choices",
                                                                          "switcher_candidates"):
        return []
    if "survey" in name or name == "read_page_ui":
        return {}
    if name == "_documents_controls_hidden":
        return 0
    return None


def run_diagnose(app: Path, stop_at: str, stop: pressing.Stop, tmp_path, monkeypatch, capsys):
    """Diagnose run through main(), stopping at `stop_at`. What it said,
    the files it wrote, the site calls it made in order, and how many links
    each survey was told it may follow."""
    mod = load(app)
    site = mod.site
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api

    def no_browser(*_args, **_kwargs):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))
    page = EmptyPage()
    monkeypatch.setattr(mod.App, "page", lambda self, *_a, **_k: page)

    calls, follows = [], []

    def stand_in(name, real):
        def answer(*args, **kwargs):
            calls.append(name)
            if name == stop_at:
                raise stop
            if name == "survey":
                given = inspect.signature(real).parameters.get("max_follow")
                follows.append(kwargs.get("max_follow", given.default if given else 0))
            if name == "address_signed_out":
                return False
            if name == "is_safe_url":
                return True
            return empty_answer(name)
        return answer

    # Where the tab is is read as the provider's own, so the look goes on.
    for name in page_calls(app) + ["address_signed_out", "is_safe_url"]:
        real = getattr(site, name, None)
        if real is not None:
            monkeypatch.setattr(site, name, stand_in(name, real))
    if discovers(app):
        def discover(self, *_a, **_k):
            calls.append("cmd_discover")
            if stop_at == "cmd_discover":
                raise stop
            return {}
        monkeypatch.setattr(mod.App, "cmd_discover", discover)

    capsys.readouterr()
    try:
        code = mod.main(["--config", str(cfg), "--diagnose"])
    except SystemExit as ended:
        code = ended.code
    said = " ".join(capsys.readouterr().out.split())
    out = tmp_path / "out"
    detailed = sorted(out.rglob("diagnose-*.json"))
    surveys = sorted(out.rglob("survey-diagnose-*.json"))
    return code, said, detailed, surveys, calls, follows, mod


def check_written(app, stop, code, said, detailed, surveys, calls, mod, stop_at):
    assert stop_at in calls, "Diagnose never reached %s here: %s" % (stop_at, calls)
    assert code in (0, None), said[-1500:]
    assert "!! " + stop.lines[0] in said, said[-1500:]
    assert len(detailed) == 1, ("the detailed file was not written", said[-1500:])
    info = json.loads(detailed[0].read_text(encoding="utf-8"))
    assert info["stopped"] == {"step": stop.step, "reason": stop.reason, "facts": stop.facts}
    assert len(surveys) == 1, said[-1500:]
    report = json.loads(surveys[0].read_text(encoding="utf-8"))
    assert report["kind"] == "paperpull-survey"
    if "stopped" in inspect.signature(mod.App.write_survey).parameters:
        # The survey beside it, the one to send, says why too.
        assert report["extra"]["stopped"]["reason"] == stop.reason
    return info


def test_the_census_is_not_vacuous():
    """Every app named as one a stop reached, and every step named."""
    names = {d.name for d in GOTO_APPS}
    assert names >= NAMED_GOTO, sorted(NAMED_GOTO - names)
    steps = {(d.name, s) for d, s in STEPS}
    assert steps >= NAMED_STEPS, sorted(NAMED_STEPS - steps)
    # A step said to sit past a row is still one of that look's calls.
    calls = {(d.name, s) for d in APPS for s in page_calls(d)}
    assert PAST_A_ROW <= calls, sorted(PAST_A_ROW - calls)


def test_every_diagnose_catches_a_stop():
    """No app is left out. Each Diagnose catches a stop, a new app's too,
    so a look a stop is first found to reach already writes its file."""
    assert APPS
    missing = [d.name for d in APPS
               if not any(isinstance(n, ast.ExceptHandler) and n.type is not None
                          and "pressing.Stop" in ast.unparse(n.type)
                          for n in ast.walk(diagnose_of(d)))]
    assert not missing, missing


@pytest.mark.parametrize("app", GOTO_APPS, ids=lambda d: d.name)
def test_a_documents_page_that_will_not_open_still_leaves_the_detailed_file(
        app, tmp_path, monkeypatch, capsys):
    code, said, detailed, surveys, calls, follows, mod = run_diagnose(
        app, "goto_documents", GOTO_STOP, tmp_path, monkeypatch, capsys)
    info = check_written(app, GOTO_STOP, code, said, detailed, surveys, calls, mod,
                         "goto_documents")
    assert info.get("documents_page_opened", False) is False
    # The page the window shows is surveyed, no link on it followed and
    # nothing past the stop pressed.
    assert all(n == 0 for n in follows), follows
    after = calls[calls.index("goto_documents") + 1:]
    assert not PRESSING_STEPS & set(after), after


@pytest.mark.parametrize("app,step", STEPS, ids=lambda v: getattr(v, "name", v))
def test_a_stop_later_in_the_look_still_leaves_the_detailed_file(
        app, step, tmp_path, monkeypatch, capsys):
    code, said, detailed, surveys, calls, follows, mod = run_diagnose(
        app, step, STEP_STOP, tmp_path, monkeypatch, capsys)
    check_written(app, STEP_STOP, code, said, detailed, surveys, calls, mod, step)
    after = calls[calls.index(step) + 1:]
    assert not PRESSING_STEPS & set(after), after
