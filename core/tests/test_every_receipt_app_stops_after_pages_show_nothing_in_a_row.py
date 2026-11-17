"""Every receipt app stops after five receipt pages in a row, new to showing
nothing, show nothing (threads of 2026-11-16, item 3).

The rule and the stop are the core's (not_shown.tried_again). These hold
that each of the eleven apps that calls it lets the stop through to its
own main and leaves the way the core means, exit code 0, a result line
that says stopped 1 and stop not_shown, a failure file of the stop's own,
and the purchases after the fifth never opened (test-plan-next.md X5, X6
and X8).

Each app's own main is driven with no console and no browser, as
test_every_receipt_resume_keeps_to_its_scope.py drives it, over a listing
an earlier run read whole. Each purchase's fetch (process_one) is a
stand-in whose receipt page shows nothing, and hands the purchase to the
core as every app's own receipt check does. That the app's own check lets
the stop through is held on its own below, through the method that calls
tried_again, and what lies between is read from the code. Every name,
number and date is invented.
"""
import ast
import datetime
import importlib.util
import json
import re
from pathlib import Path

import pytest

from paperpull_core import listing, not_shown, pressing
from paperpull_core.models import IN_STORE, ONLINE, Purchase, State

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _beside(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


census = _beside("not_shown_census_for_the_stop",
                 "test_every_receipt_app_asks_again_for_a_receipt_not_shown.py")
scope = _beside("resume_scope_for_the_stop", "test_every_receipt_resume_keeps_to_its_scope.py")

APPS = census.TRYING_APPS
IDS = [d.name for d in APPS]

STOP_WORDS = "receipt pages this run opened showed nothing"
CANARY = "CANARY-7Q3 Dana Example 4111 Elm Lane"


def test_the_eleven_are_found():
    assert {d.name for d in APPS} == census.SETS_RECEIPTS_ASIDE and len(APPS) == 11, IDS


def today() -> str:
    return datetime.date.today().isoformat()


def yesterday() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


class Home(scope.Home):
    """The app over a made-up folder, its fetch a receipt page that shows
    nothing unless the purchase is in `shows`."""

    def __init__(self, app, tmp_path, monkeypatch, capsys):
        super().__init__(app, tmp_path, monkeypatch, capsys)
        self.shows = set()
        self.whole = True
        cls = self.mod.App
        home = self

        def fetch(inst, _page, purchase, *a, **kw):
            home.fetched.append(purchase.order_number)
            if kw.get("dry_run"):
                return
            if purchase.order_number in home.shows:
                inst._record_state(purchase, State.PDF_SAVED, notes="saved")
                return
            not_shown.tried_again(inst, purchase, "The receipt page showed nothing")
        monkeypatch.setattr(cls, "process_one", fetch)

        def discover(inst, *_a, **_kw):
            home.listed += 1
            listing.started(inst)
            if home.whole:
                listing.read_whole(inst)
            return {}
        monkeypatch.setattr(cls, "cmd_discover", discover)
        self.stop_runs = []
        real_stop_run = pressing.stop_run

        def stop_run(*a, **kw):
            self.stop_runs.append(a)
            return real_stop_run(*a, **kw)
        monkeypatch.setattr(pressing, "stop_run", stop_run)

    def list_these(self, online: int, in_store: int = 0):
        """Purchases listed by an earlier run read whole, the newest first,
        ORDER-1001 the newest of each kind."""
        found = {}
        for kind, count, base in ((ONLINE, online, 1000), (IN_STORE, in_store, 2000)):
            for i in range(1, count + 1):
                day = datetime.date(2026, 11, 10) - datetime.timedelta(days=i - 1)
                p = Purchase(purchase_type=kind, purchase_date=day.isoformat(),
                             order_number="ORDER-%d" % (base + i), total="12.34",
                             summary=CANARY)
                found[p.key] = dict(p.to_dict(), state=State.DISCOVERED.value)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "discovery.json").write_text(json.dumps(found), encoding="utf-8")
        (self.out / "last-listing.json").write_text(
            json.dumps({"complete": True, "at": "2026-01-20T10:00:00"}), encoding="utf-8")
        self.found = found

    def progress(self) -> dict:
        path = self.out / "progress.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def failure_files(self):
        return sorted((self.out / "Diagnostics").glob("failure-*.json"),
                      key=lambda f: f.stat().st_mtime_ns)


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def report(home, said):
    return "%s fetched %s\n%s" % (home.app.name, home.fetched, said[-2500:])


def printed_failure_file(said: str) -> Path:
    found = re.findall(r"This run wrote a file about what went wrong: (\S+\.json)", said)
    assert found, said[-2500:]
    return Path(found[-1])


def assert_the_stop(home, said, result, ended, at: int):
    """X6.1. Stopped at the `at`-th page, as the core means."""
    assert ended in (("exit", 0), ("returned", 0)), report(home, said)
    assert len(home.fetched) == at, report(home, said)
    assert said.count(STOP_WORDS) == 1, report(home, said)
    assert result and (result["stopped"], result.get("stop")) == (1, "not_shown"), result
    assert "list_not_read" not in result, result
    assert home.stop_runs == [], "the stop went through pressing.stop_run"
    newest = home.failure_files()[-1]
    assert printed_failure_file(said).resolve() == newest.resolve(), said[-2500:]
    text = newest.read_text(encoding="utf-8")
    shown = json.loads(text)
    assert (shown["step"], shown["reason"]) == ("open the receipt",
                                                "receipt pages showed nothing in a row"), shown
    assert shown["extra"]["empty_pages_in_a_row"] == 5, shown["extra"]
    assert set(shown["extra"]) == {"empty_pages_in_a_row", "purchases_saved",
                                   "pages_that_showed_nothing_before", "skipped_as_done"}, shown
    # Counts only, never a purchase or what it held.
    assert "ORDER-" not in text and "CANARY" not in text and "Elm Lane" not in text


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_run_all_stops_at_the_fifth_empty_page(home):
    """X6.1, X8.2, X8.3."""
    home.list_these(6)
    said, result, ended = home.run(*scope.RUN_ALL)
    assert_the_stop(home, said, result, ended, 5)
    assert home.fetched == ["ORDER-100%d" % n for n in range(1, 6)], report(home, said)
    progress = home.progress()
    failed = [r for r in progress.values() if r.get("state") == State.FAILED.value]
    assert len(failed) == 5 and all(r["not_shown_days"] == [today()] for r in failed), progress
    assert any((home.out / "backups").iterdir()) if (home.out / "backups").exists() else True
    # X4.8. The list stays read whole, so Continue does not read it again.
    assert json.loads((home.out / "last-listing.json").read_text(encoding="utf-8"))["complete"]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_continue_the_same_day_stops_again_and_the_next_day_goes_past_them(home):
    """X6.2 and criterion 7."""
    home.list_these(12)
    home.run(*scope.RUN_ALL)
    home.fetched.clear()
    said, result, ended = home.run(*scope.RESUME)
    assert_the_stop(home, said, result, ended, 5)
    assert home.fetched == ["ORDER-100%d" % n for n in range(1, 6)], report(home, said)
    assert home.listed == 1, "Continue did not read the list again"
    # The next day, those five showed nothing on a day before this one.
    progress = home.progress()
    for rec in progress.values():
        if rec.get("not_shown_days"):
            rec["not_shown_days"] = [yesterday()]
    (home.out / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    home.fetched.clear()
    said, result, ended = home.run(*scope.RESUME)
    assert_the_stop(home, said, result, ended, 10)
    shown = json.loads(home.failure_files()[-1].read_text(encoding="utf-8"))
    assert shown["extra"]["pages_that_showed_nothing_before"] == 5, shown["extra"]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_save_between_keeps_the_run_going(home):
    """X10.1 and X1.3 through main. Every other page shows its receipt."""
    home.list_these(12)
    home.shows = {"ORDER-%d" % n for n in range(1001, 1013, 2)}
    said, result, ended = home.run(*scope.RUN_ALL)
    assert len(home.fetched) == 12, report(home, said)
    assert STOP_WORDS not in said
    assert result and result["stopped"] == 0 and "stop" not in result, result


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_pilot_shows_its_results_and_stops_at_the_fifth(home):
    """X5.2 and Changes item 4. One streak across the kinds."""
    home.list_these(6, 6)
    said, result, ended = home.run("--pilot")
    assert len(home.fetched) >= 5, report(home, said)
    assert_the_stop(home, said, result, ended, 5)
    assert "PILOT RESULTS" in said, report(home, said)
    assert said.index(STOP_WORDS) < said.index("PILOT RESULTS"), report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_list_not_read_whole_wins(home):
    """X4.9 and Changes item 3. A Resume after a listing that stopped
    reads the list again, which stops again, and the run's five empty pages
    leave the way an unread list leaves."""
    home.list_these(6)
    (home.out / "last-listing.json").write_text(
        json.dumps({"complete": False, "at": "2026-01-20T10:00:00"}), encoding="utf-8")
    home.whole = False
    said, result, ended = home.run(*scope.RESUME)
    assert len(home.fetched) == 5, report(home, said)
    assert ended in (("exit", 0), ("returned", 0)), report(home, said)
    assert STOP_WORDS in said and "reads the list first" in said, report(home, said)
    assert "in a few hours or tomorrow" not in said, report(home, said)
    assert result and result["stopped"] == 1 and result.get("list_not_read") == 1, result


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_pilot_table_that_fails_keeps_the_stop(home, monkeypatch):
    """Review NOTE 4. The table raising does not turn the stop into an error."""
    def broken(*_a, **_kw):
        raise RuntimeError("made to fail")
    monkeypatch.setattr(home.mod.App, "_pilot_report", broken)
    home.list_these(6, 6)
    said, result, ended = home.run("--pilot")
    assert_the_stop(home, said, result, ended, 5)
    assert "results could not be shown" in said and "made to fail" not in said, report(home, said)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_a_download_again_run_never_stops(home):
    """Review MINOR 3. A restore of receipts saved before, whose pages show
    nothing now, goes through every one as before, and so do the six after
    them that were never saved, which reach the restore's own check of the
    app's --redownload (review of the repairs, MINOR 1)."""
    home.list_these(13)
    saved = {"ORDER-%d" % n for n in range(1001, 1008)}
    progress = {k: dict(r, state=State.COMPLETED.value, downloaded_ok=True)
                for k, r in home.found.items() if r["order_number"] in saved}
    (home.out / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    said, result, ended = home.run(*scope.RUN_ALL, "--redownload")
    assert len(home.fetched) == 13, report(home, said)
    assert said.count("on 1 of 3 separate days") == 6, report(home, said)
    assert STOP_WORDS not in said, report(home, said)
    assert result and "stop" not in result, result


@pytest.mark.parametrize("app, method", census.TRYING, ids=census.TRYING_IDS)
def test_each_apps_own_receipt_check_lets_the_stop_through(app, method, tmp_path, monkeypatch,
                                                           capsys):
    """X6.5. Four new empty pages already, then the app's own method meets
    a fifth and the stop leaves it, whatever it catches."""
    mod = census.load(app)
    monkeypatch.setattr(mod, "site", census._SiteThatShowsNothing())
    inst = census.app_in(mod, tmp_path)
    for n in range(2, 6):
        not_shown.tried_again(inst, census.another("ORDER-000%d" % n), "Nothing showed")
    with pytest.raises(not_shown.NothingShown):
        census.look_in(inst, method, census.purchase())
    rec = inst.progress.get(census.purchase().key) or {}
    assert rec.get("state") == State.FAILED.value, rec
    capsys.readouterr()


# -- Pilot prints its table on the stop, read from the code ----------------------------


def _pilot_keeps_its_table(app: Path) -> bool:
    cls = census._app_class(app)
    pilot = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_pilot")
    for node in ast.walk(pilot):
        if not isinstance(node, ast.Try):
            continue
        if "process_purchases" not in ast.unparse(ast.Module(body=node.body, type_ignores=[])):
            continue
        for handler in node.handlers:
            said = ast.unparse(handler)
            if ("not_shown.STOPS" in ast.unparse(handler.type or ast.Constant(None))
                    and "_pilot_report" in said and isinstance(handler.body[-1], ast.Raise)
                    and handler.body[-1].exc is None):
                return True
    return False


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_pilot_shows_its_table_on_the_stop_and_lets_it_go_on(app):
    assert _pilot_keeps_its_table(app), app.name


# -- nothing on the way out takes the stop, read from the code (X6.6) -----------------

CORE_ON_THE_WAY = ("not_shown", "pressing", "tabs", "listing", "storage", "journal", "failure",
                   "run_reporting", "browser")

# Each one read and found harmless at 8b982c1d, by file and function. The
# test plan also named a continue in target_site.py, which sits in a for
# loop inside a finally and drops nothing, so this census does not count it.
ALLOWED = {
    # Reading documents-folders.json, not on a receipt run's way out.
    ("storage.py", "documents_roots"),
}


def _takes_it(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        caught = {"BaseException"}
    else:
        caught = {ast.unparse(n) for n in ([handler.type] if not isinstance(handler.type, ast.Tuple)
                                            else handler.type.elts)}
    if not caught & {"BaseException", "SystemExit"}:
        return False
    # One that raises again at its end lets it go on.
    last = handler.body[-1] if handler.body else None
    return not (isinstance(last, ast.Raise) and last.exc is None)


def _drops_in_finally(node: ast.Try) -> bool:
    def direct(statements, in_loop):
        for s in statements:
            if isinstance(s, ast.Return):
                return True
            if isinstance(s, (ast.Break, ast.Continue)) and not in_loop:
                return True
            if isinstance(s, (ast.For, ast.While)):
                if direct(s.body, True) or direct(s.orelse, in_loop):
                    return True
            elif isinstance(s, (ast.If, ast.With, ast.Try)):
                parts = [getattr(s, f, []) for f in ("body", "orelse", "finalbody")]
                parts += [h.body for h in getattr(s, "handlers", [])]
                if any(direct(p, in_loop) for p in parts):
                    return True
        return False
    return direct(node.finalbody, False)


def _hits(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}

    def where(node):
        while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node = parents.get(node)
        return node.name if node is not None else "<module>"
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _takes_it(node):
            yield (path.name, where(node))
        if isinstance(node, ast.Try) and node.finalbody and _drops_in_finally(node):
            yield (path.name, "return in finally" if any(
                isinstance(s, ast.Return) for s in ast.walk(ast.Module(body=node.finalbody,
                                                                       type_ignores=[])))
                   else "continue in finally")
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("suppress") and any(
                ast.unparse(a) in ("BaseException", "SystemExit") for a in node.args):
            yield (path.name, where(node))


def _files():
    for app in APPS:
        yield from sorted(p for p in app.glob("*.py"))
    for name in CORE_ON_THE_WAY:
        yield REPO / "core" / "paperpull_core" / (name + ".py")


def test_nothing_on_the_way_out_takes_the_stop():
    files = list(_files())
    assert len(files) >= 11 + len(CORE_ON_THE_WAY)
    found = {hit for f in files for hit in _hits(f)}
    assert found - ALLOWED == set(), sorted(found - ALLOWED)
    assert found == ALLOWED, "an allowed one is gone, so take it off the list"


def test_the_census_finds_what_it_looks_for(tmp_path):
    """Not a census that finds nothing because it reads nothing."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import contextlib\n"
        "def a():\n    try:\n        pass\n    except SystemExit:\n        pass\n"
        "def b():\n    try:\n        pass\n    except:\n        raise\n"
        "def c():\n    try:\n        pass\n    finally:\n        return 1\n"
        "def d():\n    with contextlib.suppress(BaseException):\n        pass\n",
        encoding="utf-8")
    assert set(_hits(sample)) == {("sample.py", "a"), ("sample.py", "return in finally"),
                                  ("sample.py", "d")}
