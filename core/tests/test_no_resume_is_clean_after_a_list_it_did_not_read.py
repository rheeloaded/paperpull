"""No Resume calls a run finished when the list it carries on from was not
read whole.

Resume reads no list of its own. It carries on from discovery.json, what
the runs before it listed. When a Discover, Pilot or Run All stopped while
it listed, at a page it could not read, a sign-in or an account the app
does not support, that list was short or empty, and Resume found nothing
left to do, said "Nothing to resume - everything in scope is complete." and
reported a clean run to the panel. The run that never listed the documents
read as finished, and the panel had just said to press Resume after it.
PayPal's business accounts showed it first.

So every listing notes in last-listing.json whether it was read to its end
(paperpull_core.listing), and Resume after a listing that stopped, or with
nothing ever listed, says so and stops as a run that stopped. This drives
each app's own main the way the panel does, with no console to answer and
no browser to attach to, so a listing stops where a real one stops when
the browser is gone, in the app's own browser(). Then Resume runs, and the
result line the panel reads has to say the run stopped, with the words the
core says it in, since a stop for some other reason would pass otherwise.
A Resume after a listing read whole has to finish clean as it always did.

A listing that does finish cannot be driven here without each provider's
site, so where each Discover notes how it ended is read from its code. It
notes a start before anything else, and that the list is whole once, after
the list is saved. Without the second every Resume would stop, and that
would only show at home.

Nothing here can reach a real browser or site. The browser is a stand-in
that refuses every attach and launch and counts each one, and the output
folder and config are made up for each test.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from paperpull_core import listing
from paperpull_core.models import State
from paperpull_core.run_reporting import PREFIX

REPO = Path(__file__).resolve().parents[2]

NOTHING_LISTED = "have been listed yet"
CUT_SHORT = "stopped before it read"
STOPS_HERE = "This run stops here"
COMPLETE = "everything in scope is complete"

# Resume as the panel presses it (gui/app.py ACTIONS).
RESUME = ("--resume", "--yes")


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


def resumes_from_a_list(app: Path) -> bool:
    """An app whose Resume carries on from documents a listing recorded, the
    Document records discovery keeps. Found by what the app is made of,
    never by its name."""
    src = entry_of(app).read_text(encoding="utf-8-sig")
    return "def cmd_resume" in src and "class Document" in src and "def cmd_discover" in src


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and resumes_from_a_list(d))
IDS = [d.name for d in APPS]


# -- where each listing notes how it ended -----------------------------------------

def discover_of(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "cmd_discover")


def notes(stmt, what: str) -> bool:
    """Whether the statement is listing.<what>(self), alone, or alone under
    an if with no else, as PayPal's is under its mark for a list that said
    more follow."""
    if isinstance(stmt, ast.If) and len(stmt.body) == 1 and not stmt.orelse:
        stmt = stmt.body[0]
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and ast.unparse(stmt.value) == "listing.%s(self)" % what)


def where_it_notes(path: Path) -> list:
    """What is wrong with where this app's Discover notes how it ended."""
    fn = discover_of(path)
    body = fn.body
    wrong = []
    if not (body and notes(body[0], "started")):
        wrong.append("something runs before the listing is noted as started")
    whole = [i for i, s in enumerate(body) if notes(s, "read_whole")]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "listing.read_whole"]
    if len(whole) != 1 or len(calls) != 1:
        wrong.append("the list is noted whole %d times, %d of them as a statement of "
                     "Discover's own" % (len(calls), len(whole)))
        return wrong
    saved = [i for i, s in enumerate(body) if "self.discovery.save(" in ast.unparse(s)]
    if not saved or max(saved) > whole[0]:
        wrong.append("the list is noted whole before it is saved")
    return wrong


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_listing_notes_how_it_ended(app):
    assert not where_it_notes(entry_of(app))


def test_the_check_of_where_a_listing_notes_finds_each_mistake(tmp_path):
    """Not a check that passes on anything."""
    good = '''
class App:
    def cmd_discover(self, quiet=False):
        listing.started(self)
        page = self.page()
        for r in site.collect(page):
            self.discovery.update(r)
        self.discovery.save()
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)
'''
    path = tmp_path / "sample_docs.py"

    def check(src):
        path.write_text(src, encoding="utf-8")
        return where_it_notes(path)
    assert check(good) == []
    late = good.replace("        listing.started(self)\n        page = self.page()\n",
                        "        page = self.page()\n        listing.started(self)\n")
    assert check(late) == ["something runs before the listing is noted as started"]
    assert check(good.replace("        listing.read_whole(self)\n", "")) == [
        "the list is noted whole 0 times, 0 of them as a statement of Discover's own"]
    early = good.replace("        listing.read_whole(self)\n", "").replace(
        "        page = self.page()\n", "        page = self.page()\n        listing.read_whole(self)\n")
    assert check(early) == ["the list is noted whole before it is saved"]
    inside = good.replace("        listing.read_whole(self)\n", "").replace(
        "            self.discovery.update(r)\n",
        "            self.discovery.update(r)\n            listing.read_whole(self)\n")
    assert check(inside) == [
        "the list is noted whole 1 times, 0 of them as a statement of Discover's own"]
    marked = good.replace("        listing.read_whole(self)\n",
                          "        if not self._cut_short:\n            listing.read_whole(self)\n")
    assert check(marked) == []


# -- the browser that is not there -------------------------------------------------

class NoBrowser:
    """sync_playwright() for a machine where the browser was closed. Every
    attach and launch is refused the way Playwright refuses one, and
    counted, so a test can say a Resume never reached for it."""

    def __init__(self):
        self.asked = 0

        def refuse(*_a, **_kw):
            self.asked += 1
            raise Exception("connect ECONNREFUSED 127.0.0.1:9")
        self.chromium = SimpleNamespace(connect_over_cdp=refuse,
                                        launch_persistent_context=refuse,
                                        launch=refuse)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


# -- each app, built as it is at home --------------------------------------------

def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


class Home:
    """One app with a made-up config and output folder, run through its own
    main with no console and no browser."""

    def __init__(self, app: Path, tmp_path: Path, monkeypatch, capsys):
        self.app = app
        self.mod = load(app)
        self.capsys = capsys
        example = app / "config.example.json"
        config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        config.update({
            "owner": "Dana Example", "output_dir": str(tmp_path / "out"),
            "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
            "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": "",
        })
        self.config = config
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.out = Path(config["output_dir"])
        self.browser = NoBrowser()
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", self.browser)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        # No console, as under the panel. A prompt reads end-of-file.
        monkeypatch.setattr("builtins.input", self._no_console)
        # How many listings began, so a Resume that reads the list again
        # before it carries on is told from one that carries on from the last.
        self.listings = 0
        began = listing.started

        def counted(app):
            self.listings += 1
            began(app)
        monkeypatch.setattr(listing, "started", counted)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def noted(self):
        """What last-listing.json says, None when there is none."""
        path = self.out / "last-listing.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def run(self, *args):
        """main with these arguments. What it printed, with its lines joined
        since a sentence is wrapped wherever a provider's name ends it, the
        result line the panel reads (None when it wrote none), and how it
        ended."""
        self.capsys.readouterr()
        try:
            ended = ("returned", self.mod.main(["--config", str(self.cfg), *args]))
        except SystemExit as e:
            ended = ("exit", e.code)
        out = self.capsys.readouterr().out
        results = [json.loads(line[len(PREFIX):]) for line in out.splitlines()
                   if line.startswith(PREFIX)]
        return " ".join(out.split()), (results[-1] if results else None), ended

    def a_document(self):
        """One document of a kind this app keeps, as its own Document class
        records it."""
        kinds = self.config.get("document_types") or ["Statement"]
        return self.mod.Document(title="Monthly Statement", category=kinds[0],
                                 summary="Monthly Statement", date="2026-01-15")

    def listed_before(self, done: bool, whole: bool = True):
        """What an earlier listing left, one document in discovery.json, done
        or not in progress.json, and how that listing ended."""
        doc = self.a_document()
        rec = doc.to_dict()
        rec["state"] = State.DISCOVERED.value
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "discovery.json").write_text(json.dumps({doc.key: rec}), encoding="utf-8")
        if done:
            finished = dict(rec, state=State.COMPLETED.value, downloaded_ok=True)
            (self.out / "progress.json").write_text(json.dumps({doc.key: finished}),
                                                    encoding="utf-8")
        (self.out / "last-listing.json").write_text(
            json.dumps({"complete": whole, "at": "2026-01-20T10:00:00"}), encoding="utf-8")
        return doc

    def run_all_stopped(self):
        """A Run All that stops while it lists, because the browser is gone."""
        asked = self.browser.asked
        said, _result, ended = self.run("--all", "--yes")
        assert self.browser.asked > asked, (
            "%s's Run All never reached for the browser, so it did not stop where "
            "this test means it to\n%s" % (self.app.name, said[-1500:]))
        assert ended[0] == "exit", (
            "%s's Run All went on without a browser\n%s" % (self.app.name, said[-1500:]))
        return said


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def stopped(result) -> bool:
    return bool(result) and result.get("stopped") == 1


# -- every app that resumes from a list -------------------------------------------

def test_there_are_apps_to_check():
    """Every document app, found by what it is made of. Not a check that
    passes because it found nobody."""
    assert len(APPS) >= 47, IDS
    assert {"paypal", "wellsfargo", "anthem", "etrade"} <= set(IDS)


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_with_nothing_ever_listed_is_not_clean(home):
    """A new install, or one whose every listing stopped before this
    existed. Resume says nothing has been listed and stops, before it asks
    for the browser."""
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said, said[-1500:]
    assert NOTHING_LISTED in said and stopped(result), said[-1500:]
    assert home.browser.asked == 0, "Resume reached for the browser with nothing to carry on from"


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_run_that_listed_nothing_is_not_clean(home):
    home.run_all_stopped()
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said, said[-1500:]
    assert NOTHING_LISTED in said and stopped(result), said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_run_that_stopped_listing_is_not_clean(home):
    """Everything an earlier listing found is done, and the latest run
    stopped while it listed. What is known is complete, the list is not.
    Said before anything else runs, since a Resume that does more than
    carry on (Anthem's other lists) can stop for its own reasons later."""
    home.listed_before(done=True)
    home.run_all_stopped()
    assert (home.noted() or {}).get("complete") is False, (
        "the Run All that stopped left the earlier listing noted as whole")
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said, said[-1500:]
    assert CUT_SHORT in said and stopped(result), said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_stops_at_its_end_after_a_list_cut_short(home):
    """The same in a dry run, which needs no browser, so the stop at the end
    of Resume is the one seen and not a stop for want of a browser."""
    home.listed_before(done=True, whole=False)
    said, result, _ended = home.run(*RESUME, "--dry-run")
    assert COMPLETE not in said and CUT_SHORT in said, said[-1500:]
    assert STOPS_HERE in said and stopped(result), said[-1500:]
    assert home.browser.asked == 0, "a dry run reached for the browser"


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_carries_on_with_what_is_known_and_then_stops(home, monkeypatch):
    """A document the stopped listing knew is still handed on to be taken,
    here in a dry run, and the run then stops all the same. A dry run never
    reaches for the browser to do it. Robinhood, USAA and Wealthfront did,
    before a dry run's first document, so with no browser theirs stopped
    there instead. A Resume that reads the list again before it takes
    anything (E*TRADE's, which needs what the list says about each row)
    stops when that listing does, with no browser to read it in."""
    doc = home.listed_before(done=False, whole=False)
    handed, returned = [], []
    take = home.mod.App.process

    def watched(app, docs, *a, **kw):
        handed.extend(d.key for d in docs)
        take(app, docs, *a, **kw)
        returned.append(True)
    monkeypatch.setattr(home.mod.App, "process", watched)
    said, result, _ended = home.run(*RESUME, "--dry-run")
    assert CUT_SHORT in said and stopped(result), said[-1500:]
    if home.listings:
        assert not handed and (home.noted() or {}).get("complete") is False, said[-1500:]
        return
    assert handed == [doc.key], (
        "the document the list held was not carried on with\n" + said[-1500:])
    assert home.browser.asked == 0, "a dry run reached for the browser\n" + said[-1500:]
    assert returned and "DRY RUN" in said and STOPS_HERE in said, said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_whole_list_still_finishes_clean(home):
    """The other side. A listing read whole with everything done is a clean
    finish, as it always was, and so is an install from before the note.
    In a dry run, since Anthem's Resume lists its other surfaces again
    otherwise, and that needs a browser."""
    home.listed_before(done=True)
    said, result, _ended = home.run(*RESUME, "--dry-run")
    assert result is not None and result["stopped"] == 0, said[-1500:]
    assert CUT_SHORT not in said and NOTHING_LISTED not in said and STOPS_HERE not in said
    (home.out / "last-listing.json").unlink()
    said, result, _ended = home.run(*RESUME, "--dry-run")
    assert result is not None and result["stopped"] == 0, said[-1500:]
    assert home.browser.asked == 0, "a dry run reached for the browser"
