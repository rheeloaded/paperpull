"""No receipt app's Resume calls a run finished when the purchase list it
carries on from was not read whole.

Resume works from discovery.json, the purchases the runs before it listed.
When a Discover, Pilot or Run All stopped while it read the purchase list,
at a sign-in, a check or a browser that was gone, that list was short or
empty. Eight receipt apps then found nothing left to do, said "Nothing to
resume - all discovered purchases are complete." and reported a clean run
to the panel, which had just said to press Resume. Six others read the list
again first, by a mark of their own, since Target's review of 0.41.0 and
the fix for a history cut short. And on an install that had never listed
anything, all fourteen said the same clean line.

So every receipt app notes in last-listing.json whether a listing was read
to its end (paperpull_core.listing), as the document apps do, and Resume
after a listing that stopped reads the list again before it takes anything.
When that listing stops too, the run stops with it. With nothing ever
listed, Resume says so and stops at once, without the browser, since a
whole history read that nobody asked for is Run All's. A Resume after a
list read whole, and on an account whose whole list held nothing, finishes
clean as it always did.

This drives each app's own main the way the panel does, with no console to
answer and no browser to attach to, so a listing stops where a real one
stops when the browser is gone, in the app's own browser(). A listing that
does finish cannot be driven without each provider's site, so where each
Discover notes how it ended is read from its code, and a Resume whose list
comes whole is shown with a stand-in listing that notes it so.

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

from paperpull_core import listing, models
from paperpull_core.models import Purchase, State
from paperpull_core.run_reporting import PREFIX

REPO = Path(__file__).resolve().parents[2]

NOTHING_LISTED = "have been listed yet"
COMPLETE = "all discovered purchases are complete"

# The runs that read the list, and Resume, as the panel presses them
# (gui/app.py ACTIONS).
READS_THE_LIST = {"discover": ("--discover",), "pilot": ("--pilot",), "run-all": ("--all", "--yes")}
RESUME = ("--resume", "--yes")

LIST = "list"


def entry_of(app: Path):
    for pattern in ("*_receipts.py", "*_docs.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


def app_class(tree):
    return next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App"), None)


def methods_of(cls) -> dict:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def keeps_purchases(app: Path) -> bool:
    """An app whose discovery keeps Purchase records, the core's, and whose
    Resume carries on from them. Found by what the app is made of, never by
    its name."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8-sig"))
    imported = any(isinstance(n, ast.ImportFrom) and n.module == "paperpull_core.models"
                   and any(a.name == "Purchase" for a in n.names) for n in tree.body)
    cls = app_class(tree)
    return bool(imported and cls and {"cmd_discover", "cmd_resume"} <= set(methods_of(cls)))


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and entry_of(d) and keeps_purchases(d))
IDS = [d.name for d in APPS]


def test_there_are_receipt_apps_to_check():
    """Every receipt app, found by what it keeps. Not a check that passes
    because it found nobody."""
    assert len(APPS) >= 14, IDS
    assert {"amazon", "walmart", "target", "apple", "uber", "kroger"} <= set(IDS)


# -- where each listing notes how it ended -----------------------------------------

def is_call(node, name: str) -> bool:
    return (isinstance(node, ast.Call) and ast.unparse(node.func) == name
            and [ast.unparse(a) for a in node.args] == ["self"] and not node.keywords)


def body_without_docstring(fn):
    body = fn.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return body[1:]
    return body


def saves(node, methods, seen=None) -> bool:
    """Whether this saves the discovery, itself or through a method of the
    app it calls, as Target's Discover does through _discover."""
    seen = set() if seen is None else seen
    if "self.discovery.save(" in ast.unparse(node):
        return True
    for call in ast.walk(node):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
                and call.func.attr in methods and call.func.attr not in seen):
            seen.add(call.func.attr)
            if saves(methods[call.func.attr], methods, seen):
                return True
    return False


def under_only_ifs(fn, target) -> bool:
    """Whether target sits in fn's own statements or under if and else alone,
    never in a loop, a with, a try or a handler, where it would be noted
    partway, or after a failure was caught."""
    def visit(statements):
        for stmt in statements:
            if target in ast.walk(stmt):
                if isinstance(stmt, ast.Expr) and stmt.value is target:
                    return True
                if isinstance(stmt, ast.If) and target not in ast.walk(stmt.test):
                    return visit(stmt.body) or visit(stmt.orelse)
                return False
        return False
    return visit(fn.body)


def where_it_notes(path: Path) -> list:
    """What is wrong with where this app's Discover notes how it ended."""
    cls = app_class(ast.parse(path.read_text(encoding="utf-8-sig")))
    methods = methods_of(cls)
    fn = methods["cmd_discover"]
    wrong = []
    body = body_without_docstring(fn)
    first = body[0] if body else None
    if not (isinstance(first, ast.Expr) and is_call(first.value, "listing.started")):
        wrong.append("something runs before the listing is noted as started")
    for name in ("started", "read_whole"):
        where = [m for m, f in methods.items() for n in ast.walk(f)
                 if isinstance(n, ast.Call) and ast.unparse(n.func) == "listing." + name]
        if where != ["cmd_discover"]:
            wrong.append("listing.%s is called %d times, in %s" % (
                name, len(where), ", ".join(where) or "nothing"))
    whole = [n for n in ast.walk(fn) if is_call(n, "listing.read_whole")]
    if len(whole) != 1:
        return wrong
    whole = whole[0]
    if not under_only_ifs(fn, whole):
        wrong.append("the list is noted whole inside a loop, a with, a try or a handler")
    before = [s for s in ast.walk(fn) if isinstance(s, ast.stmt) and s is not fn
              and s.end_lineno < whole.lineno]
    after = [s for s in ast.walk(fn) if isinstance(s, ast.stmt) and s.lineno > whole.lineno]
    if not any(saves(s, methods) for s in before) or any(
            "self.discovery.save(" in ast.unparse(s) for s in after):
        wrong.append("the list is noted whole before it is saved")
    return wrong


@pytest.mark.parametrize("app", APPS, ids=IDS)
def test_every_listing_notes_how_it_ended(app):
    assert not where_it_notes(entry_of(app))


def test_the_check_of_where_a_listing_notes_finds_each_mistake(tmp_path):
    """Not a check that passes on anything."""
    good = '''
class App:
    def cmd_discover(self, types=None, quiet=False):
        """Discovery pass."""
        listing.started(self)
        page = self.page()
        for card in site.collect_cards(page):
            self.discovery.update(card.key, card.to_dict(), save=False)
        self.discovery.save()
        if self._read_to_the_end:
            listing.read_whole(self)
        self.stats["online_discovered"] = len(self.discovery.data)
'''
    path = tmp_path / "sample_receipts.py"

    def check(src):
        path.write_text(src, encoding="utf-8")
        return where_it_notes(path)
    assert check(good) == []
    late = good.replace("        listing.started(self)\n        page = self.page()\n",
                        "        page = self.page()\n        listing.started(self)\n")
    assert check(late) == ["something runs before the listing is noted as started"]
    assert check(good.replace("            listing.read_whole(self)\n", "            pass\n")) == [
        "listing.read_whole is called 0 times, in nothing"]
    early = good.replace("        page = self.page()\n",
                         "        page = self.page()\n        listing.read_whole(self)\n"
                         ).replace("            listing.read_whole(self)\n", "            pass\n")
    assert check(early) == ["the list is noted whole before it is saved"]
    looped = good.replace("            listing.read_whole(self)\n", "            pass\n").replace(
        "            self.discovery.update(card.key, card.to_dict(), save=False)\n",
        "            self.discovery.update(card.key, card.to_dict(), save=False)\n"
        "            self.discovery.save()\n            listing.read_whole(self)\n")
    assert check(looped) == ["the list is noted whole inside a loop, a with, a try or a handler",
                             "the list is noted whole before it is saved"]
    caught = good.replace("        if self._read_to_the_end:\n            listing.read_whole(self)\n",
                          "        try:\n            self.more()\n"
                          "        except Exception:\n            listing.read_whole(self)\n")
    assert check(caught) == ["the list is noted whole inside a loop, a with, a try or a handler"]
    elsewhere = good + '''
    def cmd_resume(self):
        listing.read_whole(self)
'''
    assert check(elsewhere) == [
        "listing.read_whole is called 2 times, in cmd_discover, cmd_resume"]
    through = '''
class App:
    def cmd_discover(self, types=None, quiet=False):
        listing.started(self)
        counts = self._discover(types, quiet)
        listing.read_whole(self)
        return counts

    def _discover(self, types, quiet):
        self.discovery.save()
'''
    assert check(through) == []
    assert check(through.replace("        self.discovery.save()\n", "        return {}\n")) == [
        "the list is noted whole before it is saved"]


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
    main with no console and no browser, and what it did in order, each
    listing it began and each batch of purchases it took."""

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
        self.cfg = tmp_path / "config.json"
        self.cfg.write_text(json.dumps(config), encoding="utf-8")
        self.out = Path(config["output_dir"])
        self.browser = NoBrowser()
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", self.browser)
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        # No console, as under the panel. A prompt reads end-of-file.
        monkeypatch.setattr("builtins.input", self._no_console)
        self.did = []
        cls = self.mod.App
        discover, process = cls.cmd_discover, cls.process_purchases

        def listed(app, *a, **kw):
            self.did.append(LIST)
            return discover(app, *a, **kw)

        def took(app, purchases, *a, **kw):
            self.did.append([p.key for p in purchases])
            return process(app, purchases, *a, **kw)
        monkeypatch.setattr(cls, "cmd_discover", listed)
        monkeypatch.setattr(cls, "process_purchases", took)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

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

    def a_purchase(self):
        """One purchase of a kind this app keeps, made up."""
        kinds = getattr(self.mod, "PURCHASE_TYPES", models.PURCHASE_TYPES)
        return Purchase(purchase_type=kinds[0], purchase_date="2026-01-15",
                        order_number="1000000001", total="12.34")

    def listed_before(self, done: bool, whole=True):
        """What an earlier listing left, one purchase in discovery.json, done
        or not in progress.json, and how that listing ended, whole, stopped,
        or None for an install from before the note."""
        purchase = self.a_purchase()
        rec = purchase.to_dict()
        rec["state"] = State.DISCOVERED.value
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "discovery.json").write_text(json.dumps({purchase.key: rec}),
                                                 encoding="utf-8")
        if done:
            finished = dict(rec, state=State.COMPLETED.value, downloaded_ok=True)
            (self.out / "progress.json").write_text(json.dumps({purchase.key: finished}),
                                                    encoding="utf-8")
        if whole is not None:
            self.note(whole)
        return purchase

    def note(self, whole: bool):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "last-listing.json").write_text(
            json.dumps({"complete": whole, "at": "2026-01-20T10:00:00"}), encoding="utf-8")

    def stopped_while_listing(self, by: str = "run-all"):
        """A Discover, Pilot or Run All that stops while it lists, because the
        browser is gone."""
        asked = self.browser.asked
        said, _result, ended = self.run(*READS_THE_LIST[by])
        assert self.browser.asked > asked, (
            "%s's %s never reached for the browser, so it did not stop where "
            "this test means it to\n%s" % (self.app.name, by, said[-1500:]))
        assert ended[0] == "exit", (
            "%s's %s went on without a browser\n%s" % (self.app.name, by, said[-1500:]))
        assert LIST in self.did and not [d for d in self.did if d != LIST], (
            "%s's %s took purchases without its list\n%s" % (self.app.name, by, self.did))
        self.did.clear()
        return said


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def stopped(result) -> bool:
    return bool(result) and result.get("stopped") == 1


def finished(result) -> bool:
    return bool(result) and result.get("stopped") == 0


# -- every receipt app ------------------------------------------------------------

@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_with_nothing_ever_listed_is_not_clean(home):
    """A new install. Resume says nothing has been listed and stops, before
    it asks for the browser, and does not read the whole history in place of
    the Run All that nobody pressed."""
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said, said[-1500:]
    assert NOTHING_LISTED in said and stopped(result), said[-1500:]
    assert home.browser.asked == 0 and home.did == [], (
        "Resume reached for the browser with nothing to carry on from")


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_run_that_listed_nothing_reads_the_list(home):
    """A Run All that stopped before it listed anything, on a new install.
    Resume reads the list, and with no browser to read it in, stops."""
    home.stopped_while_listing()
    asked = home.browser.asked
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said and NOTHING_LISTED not in said, said[-1500:]
    assert home.did[:1] == [LIST], "Resume did not read the list %s" % home.did
    assert home.browser.asked > asked and stopped(result), said[-1500:]


@pytest.mark.parametrize("by", list(READS_THE_LIST))
@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_run_that_stopped_listing_reads_the_list_again(home, by):
    """The case measured on 2026-10-06. Everything an earlier listing found
    is done, and the latest Discover, Pilot or Run All stopped while it
    listed. What is known is complete, the list is not, so Resume reads it
    again, and stops with it."""
    home.listed_before(done=True)
    home.stopped_while_listing(by)
    said, result, _ended = home.run(*RESUME)
    assert COMPLETE not in said, said[-1500:]
    assert home.did[:1] == [LIST], "Resume did not read the list again %s" % home.did
    assert stopped(result), said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_reads_the_list_before_it_takes_anything(home):
    """A purchase the earlier listing found and nobody has downloaded, and a
    Run All that stopped while it listed. Resume reads the list before it
    takes the purchase, so with no browser it stops there, the purchase left
    for the next run."""
    home.listed_before(done=False)
    home.stopped_while_listing()
    said, result, _ended = home.run(*RESUME)
    assert home.did[:1] == [LIST], "Resume took purchases before it read the list %s" % home.did
    assert stopped(result), said[-1500:]


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_carries_on_once_the_list_comes_whole(home, monkeypatch):
    """The other half. When the list read again comes whole, Resume goes on
    with the purchases not done and finishes clean. No provider's site can
    be driven here, so the second listing is a stand-in that notes the list
    whole the way a Discover that reached its end does, and the purchases
    are watched as they are handed over rather than downloaded."""
    purchase = home.listed_before(done=False)
    home.stopped_while_listing()

    def whole(app, *_a, **_kw):
        home.did.append(LIST)
        listing.started(app)
        listing.read_whole(app)
        return {}

    def took(app, purchases, *_a, **_kw):
        home.did.append([p.key for p in purchases])
    monkeypatch.setattr(home.mod.App, "cmd_discover", whole)
    monkeypatch.setattr(home.mod.App, "process_purchases", took)
    asked = home.browser.asked
    said, result, _ended = home.run(*RESUME)
    assert home.did == [LIST, [purchase.key]], home.did
    assert finished(result), said[-1500:]
    assert home.browser.asked == asked, "the purchases were handed over, not downloaded"


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_resume_after_a_whole_list_still_finishes_clean(home):
    """A listing read whole with everything done is a clean finish, as it
    always was, and Resume does not read the list again. So is an install
    from before the note, which has a list to carry on from."""
    home.listed_before(done=True)
    said, result, _ended = home.run(*RESUME)
    assert finished(result) and COMPLETE in said, said[-1500:]
    assert NOTHING_LISTED not in said
    (home.out / "last-listing.json").unlink()
    said, result, _ended = home.run(*RESUME)
    assert finished(result) and COMPLETE in said, said[-1500:]
    assert home.did == [] and home.browser.asked == 0, home.did


@pytest.mark.parametrize("home", APPS, ids=IDS, indirect=True)
def test_an_account_whose_whole_list_held_nothing_still_finishes_clean(home):
    """A list read to its end that held no purchase is an account with
    nothing bought, not a new install, and Resume has nothing to do."""
    home.out.mkdir(parents=True)
    (home.out / "discovery.json").write_text("{}", encoding="utf-8")
    home.note(whole=True)
    said, result, _ended = home.run(*RESUME)
    assert finished(result) and NOTHING_LISTED not in said, said[-1500:]
    assert home.did == [] and home.browser.asked == 0, home.did
