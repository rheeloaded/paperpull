"""A Discover whose documents page would not open stops the run.

Twenty document apps open their documents page at the top of Discover, ask
again after a session check, and when it still would not open they printed
a line and returned. Pilot then said there was nothing in scope to pilot,
or worked through documents an earlier run had listed, Run All did the
same, and the result line the panel reads said the run had not stopped. A
run that never read the list read as finished, while Resume, which reads
the note every Discover leaves (paperpull_core.listing), said the same run
had stopped before it read the whole list.

So a Discover that leaves before its list is noted whole stops the run. Or
it marks the run as one that did not read its list, and Pilot, Run All and
Resume, when they ask Discover not to stop, stop on that mark on their way
out. Anthem's Run All does that, since it reads the member documents, ID
cards and letters after the EOBs, each from a list of its own. A Discover
account that has moved to Capital One is no stop. Its list is the whole of
it with nothing in it, so neither the run nor a Resume after it stops for
want of the list.

Two checks, each finding its apps by what their code does. The first reads
every app's Discover for a return before its list is noted whole. The
second drives the main of every app whose Discover asks its opener twice
and acts on the second answer, with an opener that never opens, and reads
how Pilot, Run All and Discover end and the result line the panel reads.
Twenty-five other document apps ask their opener twice and read whatever
page is open however the second answer went, which neither check covers.

Nothing here can reach a real browser or site. The browser is a stand-in
that answers whatever it is asked, the opener and the session check are
replaced, and the output folder and config are made up for each test.
"""
import ast
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from paperpull_core.run_reporting import PREFIX

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


def methods_of(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            return {n.name: n for n in node.body if isinstance(n, ast.FunctionDef)}
    return {}


ENTRIES = sorted(entry_of(d) for d in (REPO / "apps").iterdir()
                 if d.is_dir() and entry_of(d) and "cmd_discover" in methods_of(entry_of(d)))
IDS = [p.parent.name for p in ENTRIES]


# -- reading the code ------------------------------------------------------------------

def self_attr(node):
    """The name X of self.X, or None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and node.value.id == "self":
        return node.attr
    return None


def raises_system_exit(node) -> bool:
    exc = node.exc if isinstance(node, ast.Raise) else None
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def in_statements(statements):
    for stmt in statements:
        yield from ast.walk(stmt)


def called_on_self(stmt):
    """The method a statement calls on self, when the statement is that call."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        return self_attr(stmt.value.func)
    return None


def stoppers(methods) -> set:
    """The methods that always raise SystemExit, at the top of their body or
    through another that does, with no return of their own that could leave
    before it."""
    found = set()
    while True:
        more = {name for name, fn in methods.items() if name not in found
                and not any(isinstance(s, ast.Return) for s, _block in blocks(fn))
                and any(raises_system_exit(s) or called_on_self(s) in found
                        for s in fn.body)}
        if not more:
            return found
        found |= more


def set_true(statements) -> set:
    """The attributes these statements, themselves and not what is inside
    them, set to True."""
    out = set()
    for stmt in statements:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                and stmt.value.value is True:
            out |= {self_attr(t) for t in stmt.targets} - {None}
    return out


def stop_flags(methods):
    """The marks and the methods that stop on them, as (flags, stops). A
    mark is an attribute a method tests in an if whose body raises
    SystemExit, and that a method other than __init__ sets to True."""
    tested = {}
    for name, fn in methods.items():
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and any(
                    raises_system_exit(n) for n in in_statements(node.body)):
                for attr in {self_attr(n) for n in ast.walk(node.test)} - {None}:
                    tested.setdefault(attr, set()).add(name)
    set_somewhere = set()
    for name, fn in methods.items():
        if name != "__init__":
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                        and node.value.value is True:
                    set_somewhere |= {self_attr(t) for t in node.targets} - {None}
    flags = set(tested) & set_somewhere
    return flags, {name for attr in flags for name in tested[attr]}


def blocks(fn):
    """Each statement in fn with the block that holds it, nested functions
    left out, since they are not run where they are written."""
    def visit(statements):
        for stmt in statements:
            yield stmt, statements
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, field, None)
                if isinstance(inner, list):
                    yield from visit(inner)
            for handler in getattr(stmt, "handlers", None) or []:
                yield from visit(handler.body)
            for case in getattr(stmt, "cases", None) or []:
                yield from visit(case.body)
    yield from visit(fn.body)


def noted_whole_at(fn):
    """The line where Discover notes its list as read whole, or None."""
    lines = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "listing.read_whole"]
    return min(lines) if lines else None


def first_printed(statements) -> str:
    """The first line these statements print, themselves and not a block
    inside them, which may have left on its own way."""
    for stmt in statements:
        node = stmt.value if isinstance(stmt, ast.Expr) else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "print" and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value.strip()
    return ""


def ways_out_before_the_list(path: Path) -> list:
    """Each return in Discover that leaves before the list is noted whole,
    or in an app that never notes it, before Discover's last statement, as
    (line, the first line printed on the way there, whether it stops).

    It stops when a statement before it in its own block raises SystemExit,
    calls a method that always does, or sets a mark a method stops on. A
    stop or a mark only some of the time, under an if inside the block,
    does not count."""
    methods = methods_of(path)
    fn = methods["cmd_discover"]
    whole = noted_whole_at(fn)
    flags, _stops = stop_flags(methods)
    always = stoppers(methods)
    out = []
    for stmt, block in blocks(fn):
        if not isinstance(stmt, ast.Return) or stmt is fn.body[-1]:
            continue
        if whole is not None and stmt.lineno > whole:
            continue
        before = block[:block.index(stmt)]
        stops = any(raises_system_exit(s) or called_on_self(s) in always for s in before) \
            or bool(set_true(before) & flags)
        out.append((stmt.lineno, first_printed(before), stops))
    return out


def quiet_ways_out(path: Path) -> list:
    """What in this app leaves Discover before its list is read and lets
    the run finish clean."""
    return ["cmd_discover line %d, after %r" % (line, said)
            for line, said, stops in ways_out_before_the_list(path) if not stops]


def tells_discover_not_to_stop(fn) -> list:
    """The lines where fn calls self.cmd_discover with a finish that may be
    False."""
    return [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
            and self_attr(n.func) == "cmd_discover"
            and any(k.arg == "finish" and not (isinstance(k.value, ast.Constant)
                                               and k.value.value is True)
                    for k in n.keywords)]


# The commands that read the list and report how the run went. Diagnose and
# Record are surveys, which go on whatever the list does and report nothing.
COMMANDS = ("cmd_pilot", "cmd_run", "cmd_resume")


def ways_out_without_a_stop(path: Path) -> list:
    """In an app whose Discover marks a run instead of stopping it, each
    way out that does not stop on the mark. Discover itself has to stop on
    it, and so does every way out of Pilot, Run All and Resume when they
    tell Discover not to, from that call on."""
    methods = methods_of(path)
    flags, stops = stop_flags(methods)
    discover = methods["cmd_discover"]
    if not set_true([n for n in ast.walk(discover) if isinstance(n, ast.stmt)]) & flags:
        return []
    wrong = []
    if not {self_attr(n.func) for n in ast.walk(discover) if isinstance(n, ast.Call)} & stops:
        wrong.append("cmd_discover never stops on the mark")
    for name in COMMANDS:
        fn = methods.get(name)
        told = tells_discover_not_to_stop(fn) if fn else []
        if not told:
            continue
        for stmt, block in blocks(fn):
            if isinstance(stmt, ast.Return) and stmt.lineno > min(told):
                at = block.index(stmt)
                if at == 0 or called_on_self(block[at - 1]) not in stops:
                    wrong.append("%s returns at line %d without stopping on the mark"
                                 % (name, stmt.lineno))
        if called_on_self(fn.body[-1]) not in stops:
            wrong.append("%s ends without stopping on the mark" % name)
    return wrong


# -- every app, read --------------------------------------------------------------------

def test_there_are_apps_to_read():
    assert len(ENTRIES) >= 60, IDS


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_discover_never_leaves_before_its_list_and_lets_the_run_finish_clean(entry):
    assert not quiet_ways_out(entry)


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_a_run_marked_as_not_having_its_list_stops_on_its_way_out(entry):
    assert not ways_out_without_a_stop(entry)


def test_the_app_that_marks_instead_of_stopping_is_read_for_its_ways_out():
    """The second check passes on an app with no mark, so it has to be seen
    reaching the one that keeps one."""
    anthem = REPO / "apps" / "anthem" / "anthem_docs.py"
    flags, stops = stop_flags(methods_of(anthem))
    assert flags and stops
    assert tells_discover_not_to_stop(methods_of(anthem)["cmd_run"])


# -- the rule, on samples ---------------------------------------------------------------

OLD = '''
class App:
    def cmd_discover(self, quiet=False):
        listing.started(self)
        page = self.page()
        if not site.ensure_statements(page):
            self.check_session(page)
            if not site.ensure_statements(page):
                print("Could not open your statements. Sign in and open")
                print("Statements in the browser, then try again.")
                return 0
        self.check_session(page)
        for d in site.collect(page):
            self.discovery.update(d)
        self.discovery.save()
        listing.read_whole(self)
        self.stats["discovered"] = len(self.discovery.data)
        if quiet:
            return 0
        print("Discovery complete.")
        return 1
'''

MARKED = OLD.replace(
    '                return 0\n        self.check_session(page)',
    '                self._unread = True\n'
    '                if finish:\n'
    '                    self._stop_if_unread()\n'
    '                return 0\n'
    '        self.check_session(page)').replace(
    "def cmd_discover(self, quiet=False):", "def cmd_discover(self, quiet=False, finish=True):") + '''
    def _stop_if_unread(self):
        if self._unread:
            print("The list was not read.")
            raise SystemExit(0)

    def cmd_run(self, mode):
        others = mode == "all"
        self.cmd_discover(finish=not others)
        docs = self._select()
        if not docs:
            print("Nothing to download.")
            self._stop_if_unread()
            return
        self.process(docs)
        if others:
            self.cmd_letters()
        self._stop_if_unread()
'''


def sample(tmp_path, src, app="sample"):
    path = tmp_path / app / ("%s_docs.py" % app)
    path.parent.mkdir(exist_ok=True)
    path.write_text(src, encoding="utf-8")
    return path


def line_of(src: str, text: str) -> int:
    return src[:src.index(text)].count("\n") + 1


def test_the_rule_catches_the_old_way(tmp_path):
    found = quiet_ways_out(sample(tmp_path, OLD))
    assert found == ["cmd_discover line %d, after 'Could not open your statements. "
                     "Sign in and open'" % line_of(OLD, "                return 0")], found


def test_a_stop_in_place_of_the_return_passes(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                raise SystemExit(0)\n        self.check_session")
    assert not quiet_ways_out(sample(tmp_path, src))


@pytest.mark.parametrize("stop", [
    "                raise SystemExit(0)\n",
    "                self._gone()\n",
], ids=["raises", "calls what always raises"])
def test_a_stop_before_the_return_passes(tmp_path, stop):
    src = OLD.replace("                return 0\n        self.check_session",
                      stop + "                return 0\n        self.check_session") + '''
    def _gone(self):
        raise SystemExit(0)
'''
    assert not quiet_ways_out(sample(tmp_path, src))


def test_a_stop_only_some_of_the_time_does_not_pass(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                if quiet:\n                    raise SystemExit(0)\n"
                      "                return 0\n        self.check_session")
    assert quiet_ways_out(sample(tmp_path, src))


def test_a_helper_that_can_return_before_it_raises_is_no_stop(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                self._gone()\n                return 0\n"
                      "        self.check_session") + '''
    def _gone(self):
        if self.args.quiet:
            return
        raise SystemExit(0)
'''
    assert quiet_ways_out(sample(tmp_path, src))


def test_a_return_in_a_match_case_is_found(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                raise SystemExit(0)\n        self.check_session").replace(
        "        for d in site.collect(page):\n",
        "        match self.args.kind:\n            case \"none\":\n                return 0\n"
        "        for d in site.collect(page):\n")
    assert quiet_ways_out(sample(tmp_path, src)) == [
        "cmd_discover line %d, after ''" % (line_of(src, '            case "none":') + 1)]


def test_a_return_once_the_list_is_whole_is_no_way_out_before_it(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                raise SystemExit(0)\n        self.check_session")
    path = sample(tmp_path, src)
    assert ways_out_before_the_list(path) == []


def test_a_return_in_a_function_inside_discover_is_not_a_way_out_of_it(tmp_path):
    src = OLD.replace("                return 0\n        self.check_session",
                      "                raise SystemExit(0)\n        self.check_session").replace(
        "        self.check_session(page)\n        for d",
        "        self.check_session(page)\n\n        def keep(d):\n            return d\n\n"
        "        for d")
    assert ways_out_before_the_list(sample(tmp_path, src)) == []


def test_an_app_without_a_listing_note_is_held_to_its_last_statement(tmp_path):
    """A receipt app notes no listing, so every return but its last
    statement is a way out before its list."""
    src = OLD.replace("        listing.read_whole(self)\n", "")
    found = quiet_ways_out(sample(tmp_path, src))
    assert found[1:] == ["cmd_discover line %d, after ''"
                         % (line_of(src, "        if quiet:") + 1)], found


def test_a_mark_that_is_stopped_on_passes(tmp_path):
    path = sample(tmp_path, MARKED)
    assert not quiet_ways_out(path)
    assert not ways_out_without_a_stop(path)


def test_a_mark_nothing_stops_on_is_not_a_mark(tmp_path):
    src = MARKED.replace("            raise SystemExit(0)\n", "            return\n")
    assert quiet_ways_out(sample(tmp_path, src))


def test_a_mark_set_only_some_of_the_time_does_not_pass(tmp_path):
    src = MARKED.replace("                self._unread = True\n",
                         "                if quiet:\n                    self._unread = True\n")
    assert quiet_ways_out(sample(tmp_path, src))


def test_discover_has_to_stop_on_its_own_mark(tmp_path):
    src = MARKED.replace("                if finish:\n                    self._stop_if_unread()\n",
                         "")
    assert ways_out_without_a_stop(sample(tmp_path, src)) == [
        "cmd_discover never stops on the mark"]


def test_a_command_that_tells_discover_not_to_stop_has_to_stop_on_the_mark(tmp_path):
    early = MARKED.replace('            print("Nothing to download.")\n'
                           '            self._stop_if_unread()\n',
                           '            print("Nothing to download.")\n')
    found = ways_out_without_a_stop(sample(tmp_path, early))
    assert len(found) == 1 and found[0].startswith("cmd_run returns at line "), found
    late = MARKED[:MARKED.rindex("        self._stop_if_unread()\n")]
    assert ways_out_without_a_stop(sample(tmp_path, late)) == [
        "cmd_run ends without stopping on the mark"]


# -- driving each app's main ------------------------------------------------------------

def site_test(node):
    """X when node is `not site.X(...)`."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) \
            and isinstance(node.operand, ast.Call):
        f = node.operand.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == "site":
            return f.attr
    return None


def opener_of(path: Path):
    """The site function Discover asks whether its page is open, asks again
    after a session check, and acts on the second answer of, or None."""
    fn = methods_of(path).get("cmd_discover")
    for node in ast.walk(fn) if fn else ():
        name = isinstance(node, ast.If) and site_test(node.test)
        if name and any(isinstance(s, ast.If) and site_test(s.test) == name
                        for s in node.body):
            return name
    return None


ASKERS = [p.parent for p in ENTRIES if opener_of(p)]
ASKER_IDS = [d.name for d in ASKERS]


def other_lists(path: Path) -> list:
    """The other lists Run All reads after Discover, each a command of the
    app's own that cmd_run calls."""
    fn = methods_of(path)["cmd_run"]
    return sorted({self_attr(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and (self_attr(n.func) or "").startswith("cmd_")} - {"cmd_discover"})


class Context:
    """The signed-in context a run attaches to, with no tab of the person's
    open, so the run opens one of its own. A tab answers whatever it is
    asked, since nothing here reads it."""

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
        self.context = Context()
        browser = MagicMock(name="browser")
        browser.contexts = [self.context]

        def launch(*_a, **_kw):
            raise AssertionError("the run launched a browser of its own instead of attaching")
        self.chromium = SimpleNamespace(connect_over_cdp=lambda *_a, **_kw: browser,
                                        launch_persistent_context=launch, launch=launch)

    def __call__(self):
        return self

    def start(self):
        return self

    def stop(self):
        return None


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
    """One app with a made-up config and output folder, whose documents page
    never opens, run through its own main with no console."""

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
        import playwright.sync_api as sync_api
        monkeypatch.setattr(sync_api, "sync_playwright", Playwright())
        monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)
        monkeypatch.setattr("builtins.input", self._no_console)
        # The page never opens, and the session is live, so what is seen is
        # what Discover does with a page that would not open.
        self.opener = opener_of(entry_of(app))
        self.asked = 0

        def never(*_a, **_kw):
            self.asked += 1
            return False
        monkeypatch.setattr(self.mod.site, self.opener, never)
        monkeypatch.setattr(self.mod.App, "check_session", lambda *_a, **_kw: False)
        # The other lists Run All reads, each counted rather than read.
        self.read = {}
        for name in other_lists(entry_of(app)):
            def counted(_app, *_a, _name=name, **_kw):
                self.read[_name] = self.read.get(_name, 0) + 1
            monkeypatch.setattr(self.mod.App, name, counted)

    @staticmethod
    def _no_console(*_a, **_kw):
        raise EOFError

    def run(self, *args):
        """main with these arguments. What it printed, its lines joined, the
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

    def listed_nothing(self) -> bool:
        noted = self.out / "last-listing.json"
        found = self.out / "discovery.json"
        return (json.loads(noted.read_text(encoding="utf-8"))["complete"] is False
                and (not found.exists() or not json.loads(found.read_text(encoding="utf-8"))))


@pytest.fixture
def home(request, tmp_path, monkeypatch, capsys):
    return Home(request.param, tmp_path, monkeypatch, capsys)


def stopped(result) -> bool:
    return bool(result) and result.get("stopped") == 1


def test_the_apps_that_ask_their_opener_twice_are_found():
    """Found by what their Discover does, never by a name. Not a check that
    passes because it found nobody."""
    assert len(ASKERS) >= 20, ASKER_IDS
    assert {"aafmaa", "anthem", "discovercard", "mtb", "pge", "wealthfront"} <= set(ASKER_IDS)
    assert other_lists(REPO / "apps" / "anthem" / "anthem_docs.py") == [
        "cmd_documents", "cmd_id_cards", "cmd_letters"]


@pytest.mark.parametrize("home", ASKERS, ids=ASKER_IDS, indirect=True)
def test_a_pilot_whose_documents_page_will_not_open_stops(home):
    said, result, ended = home.run("--pilot")
    assert home.asked == 2, "%s asked its opener %d times\n%s" % (
        home.app.name, home.asked, said[-1500:])
    assert ended == ("exit", 0) and stopped(result), said[-1500:]
    assert home.listed_nothing()


@pytest.mark.parametrize("home", ASKERS, ids=ASKER_IDS, indirect=True)
def test_run_all_reads_every_other_list_and_then_stops(home):
    """Run All still reads whatever other lists it reads after Discover,
    Anthem's member documents, ID cards and letters, and then stops."""
    said, result, ended = home.run("--all", "--yes")
    assert home.asked == 2, said[-1500:]
    assert ended == ("exit", 0) and stopped(result), said[-1500:]
    assert home.read == {name: 1 for name in other_lists(entry_of(home.app))}, home.read
    assert home.listed_nothing()


@pytest.mark.parametrize("home", ASKERS, ids=ASKER_IDS, indirect=True)
def test_a_discover_whose_documents_page_will_not_open_stops(home):
    said, result, ended = home.run("--discover")
    assert home.asked == 2, said[-1500:]
    assert ended == ("exit", 0), said[-1500:]
    assert result is None or stopped(result), said[-1500:]
    assert home.listed_nothing()


@pytest.mark.parametrize("home", [REPO / "apps" / "discovercard"], ids=["discovercard"],
                         indirect=True)
def test_a_discover_account_moved_to_capital_one_still_ends_clean(home, monkeypatch):
    """The person is told what happened and that there is nothing to fix,
    and with nothing listed before, neither the run nor a Resume after it
    is called stopped, since no later run could change it. Its list is
    noted as read whole, with nothing in it, so Resume agrees with Pilot
    and Run All. A statement listed earlier and never downloaded still
    stops the run that reaches for it, as it always did."""
    monkeypatch.setattr(home.mod.site, "looks_moved_to_capital_one", lambda _page: True)
    for args in (("--pilot",), ("--all", "--yes"), ("--discover",)):
        said, result, ended = home.run(*args)
        assert "has moved to Capital One" in said and "nothing to fix" in said, said[-1500:]
        assert ended == ("returned", 0), said[-1500:]
        assert result is None or result["stopped"] == 0, said[-1500:]
        assert json.loads((home.out / "last-listing.json").read_text(
            encoding="utf-8"))["complete"] is True
        said, result, ended = home.run("--resume", "--yes")
        assert ended == ("returned", 0) and result["stopped"] == 0, said[-1500:]
        assert "stopped before it read" not in said and "listed yet" not in said, said[-1500:]
