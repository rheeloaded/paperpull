"""Every browser a test starts for an app to attach to has drawn a page
before the app attaches.

A browser that has only just started is not the one login.bat leaves open
at home. On CI a fresh Chrome's first navigation came back net::ERR_ABORTED
after about five seconds, which is how a browser answers when its network
service restarts under it, and about one fresh start in thirteen loses its
first tab. A fixture that hands such a browser straight to the app fails
on the app's very first goto. The GitHub, Walmart, Best Buy and Target
fixtures were guarded against it one by one on 2026-10-01, and six page
check files added on 2026-10-03 came without the guard. Target's failed on
CI the same day, run 37123796050, with the abort on its first goto.

So a test that starts a browser with a debugging port hands it over only
once a tab has drawn a page. testkit.drawn_browser does that in one place.
A fixture of its own does it the same way, starting the browser inside a
loop that ends in a failure when no browser gets there, and leaving the
loop only by a break that a tab decided, one it opened and sent to a page.
A test is found here by what it does, giving a browser the argument that
opens a debugging port. The argument is followed through the names and
functions of its module, a function it imports from testkit or from a file
beside it, and a string holding a whole command line, and only a docstring,
an assert or a comparison is left out. This file names the argument and
starts no browser, so it is left out too.

An app that works in the first tab it finds, as Target does, rather than
in a tab it opens for itself, is handed the browser with only_tab, so that
the tab that drew is the only one it can find.

It needs no browser.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TESTKIT = REPO / "core" / "paperpull_core" / "testkit.py"

# The argument a browser is started with for an app to attach to, as a
# word of its own, so a command line written as one string counts too.
PORT_FLAG = re.compile(r"(?:^|\s)--remote-debugging-port(?:=|\s|$)")

HOW = ("Start it with testkit.drawn_browser, and with only_tab=True when the app works "
       "in the first tab it finds rather than a tab of its own.")

FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)


def files_to_read():
    roots = [REPO / "core" / "tests", REPO / "gui" / "tests"]
    roots += sorted(p / "tests" for p in (REPO / "apps").iterdir() if (p / "tests").is_dir())
    here = Path(__file__).resolve()
    return [path for root in roots if root.is_dir() for path in sorted(root.rglob("*.py"))
            if path.resolve() != here]


def _name(call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _ids(nodes) -> set:
    return {id(n) for node in nodes for n in ast.walk(node)}


def _locals(fn) -> set:
    """The names fn binds itself, its parameters, what it assigns and the
    functions it defines, each of which hides a name of the module."""
    out = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    out |= {n.name for n in ast.walk(fn) if isinstance(n, FUNCTION) and n is not fn}
    for args in (n for n in ast.walk(fn) if isinstance(n, ast.arguments)):
        out |= {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs
                + [args.vararg, args.kwarg] if a is not None}
    return out


def _own(nodes):
    """The nodes under these, without going into a loop or a function of
    their own, whose breaks are their own."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.For, ast.While, ast.Lambda) + FUNCTION):
                stack.append(child)


def _module_level(tree):
    """The statements a module runs when it is imported, into an if, a try
    or a with, never into a function or a class."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, FUNCTION + (ast.ClassDef,)):
            continue
        yield node
        stack.extend(n for n in ast.iter_child_nodes(node) if isinstance(n, ast.stmt))


def _port_flags(tree) -> list:
    """Every string that gives a browser a debugging port, left out where it
    is only looked for, in an assert or a comparison, or only told about,
    in a docstring."""
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and PORT_FLAG.search(n.value)]
    if not found:
        return []
    told = _ids(n for n in ast.walk(tree) if isinstance(n, (ast.Assert, ast.Compare)))
    told |= {id(n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n for n in found if id(n) not in told]


class Module:
    """One module's functions, which of them start a browser, which open a
    tab in one and send it to a page, and what it imports of those from
    the modules in others, keyed by the name an import gives them. A module
    in others is read on its own, so this follows one import and no more."""

    def __init__(self, path: Path, source: str = None, others=None, tree=None):
        self.path = path
        self.tree = tree or ast.parse(source if source is not None
                                      else path.read_text(encoding="utf-8"))
        others = others or {}
        self.functions = {}
        for stmt in self.tree.body:
            if isinstance(stmt, FUNCTION):
                self.functions[stmt.name] = stmt
            elif isinstance(stmt, ast.ClassDef):
                self.functions.update({"%s.%s" % (stmt.name, fn.name): fn for fn in stmt.body
                                       if isinstance(fn, FUNCTION)})
        self.drawn_calls = [n for n in ast.walk(self.tree)
                            if isinstance(n, ast.Call) and _name(n) == "drawn_browser"]
        self.aliases, self.imported = {}, {}
        for node in _module_level(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[-1] in others and (a.asname or "." not in a.name):
                        self.aliases[a.asname or a.name] = others[a.name.split(".")[-1]]
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name in others:
                        self.aliases[a.asname or a.name] = others[a.name]
                    elif node.module and node.module.split(".")[-1] in others:
                        self.imported[a.asname or a.name] = (others[node.module.split(".")[-1]],
                                                             a.name)
        flags = _port_flags(self.tree)
        self.flag_names = {local for local, (mod, name) in self.imported.items()
                           if name in mod.flag_names}
        self.loose, self.starters, self.deciders, self.opens, self.goes = [], set(), set(), set(), set()
        self._reads, self._flags_in, self.starter_keys, self.decider_keys = {}, {}, set(), set()
        if not flags and not self.flag_names and not self.aliases and not self.imported:
            # Nothing here starts a browser or could, so there is nothing to follow.
            return
        flag_ids = {id(f) for f in flags}
        # The names of the module that hold the argument, however far it is
        # handed from one to the next.
        assigns = [n for n in _module_level(self.tree)
                   if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None]
        while True:
            more = set()
            for a in assigns:
                if any(id(n) in flag_ids or (isinstance(n, ast.Name) and n.id in self.flag_names)
                       for n in ast.walk(a.value)):
                    targets = a.targets if isinstance(a, ast.Assign) else [a.target]
                    more |= {t.id for target in targets for t in ast.walk(target)
                             if isinstance(t, ast.Name)} - self.flag_names
            if not more:
                break
            self.flag_names |= more
        # Anything else outside a function starts a browser at import and
        # can wait for nothing.
        held = _ids(self.functions.values()) | _ids(a.value for a in assigns)
        self.loose = sorted(f.lineno for f in flags if id(f) not in held)
        # What each function reads by name, less the names it binds itself,
        # since a test's parameter named after a fixture is the fixture's
        # value, not the function. An imported module's functions are read
        # as the module's name and theirs.
        for name, fn in self.functions.items():
            hidden = _locals(fn)
            reads = []
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in hidden:
                    reads.append((n.id, n))
                elif (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                      and n.value.id in self.aliases and n.value.id not in hidden):
                    reads.append(("%s.%s" % (n.value.id, n.attr), n))
            self._reads[name] = reads
            self._flags_in[name] = [n for n in ast.walk(fn) if id(n) in flag_ids]
        self.starter_keys = self._closure(
            {name for name in self.functions if self._flags_in[name]
             or any(key in self.flag_names for key, _ in self._reads[name])},
            lambda mod, name: name in mod.starters)
        self.starters = {key for key in self.starter_keys if key in self.functions}
        opens = self._closure({name for name, fn in self.functions.items() if any(
            (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "new_page")
            or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "/json/new" in n.value)
            for n in ast.walk(fn))}, lambda mod, name: name in mod.opens)
        goes = self._closure({name for name, fn in self.functions.items() if any(
            (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "goto")
            or (isinstance(n, ast.Constant) and isinstance(n.value, str) and "/json/new?" in n.value)
            for n in ast.walk(fn))}, lambda mod, name: name in mod.goes)
        self.opens = {key for key in opens if key in self.functions}
        self.goes = {key for key in goes if key in self.functions}
        # A tab decides only when it was opened and sent to a page by
        # something other than what started the browser.
        self.deciders = (self.opens & self.goes) - self.starters
        self.decider_keys = self.deciders | {key for key in opens & goes
                                             if key not in self.functions
                                             and key not in self.starter_keys}

    def _outside(self, key):
        """The module and the name there for a name this one imports."""
        if key in self.imported:
            return self.imported[key]
        alias, _, attr = key.partition(".")
        if attr and alias in self.aliases:
            return self.aliases[alias], attr
        return None

    def _closure(self, base, outside_has) -> set:
        """These functions, every imported one outside_has holds for, and
        every function here that names one of them, as keys."""
        found = set(base)
        for name in self.functions:
            for key, _ in self._reads[name]:
                there = self._outside(key)
                if there and outside_has(*there):
                    found.add(key)
        while True:
            more = {name for name in self.functions
                    if name not in found and any(key in found for key, _ in self._reads[name])}
            if not more:
                return found
            found |= more

    def _key(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return "%s.%s" % (node.value.id, node.attr)
        return None

    def _launches(self, name) -> list:
        """Where the function starts a browser, as (key, node), by giving it
        the argument itself or through a function that does. The argument
        handed to such a function is part of that function's start."""
        fn = self.functions[name]
        handed = set()
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and self._key(call.func) in self.starter_keys - {name}:
                handed |= _ids(call.args + [k.value for k in call.keywords])
        sites = [(None, n) for n in self._flags_in[name] if id(n) not in handed]
        sites += [(key, n) for key, n in self._reads[name]
                  if key in self.flag_names and id(n) not in handed]
        sites += [(key, n) for key, n in self._reads[name]
                  if key in self.starter_keys and key != name]
        return sites

    def _decided(self, test, trusted) -> bool:
        """Whether an if's test can be true only once a tab drew, read through
        and, or, and a comparison with None."""
        if isinstance(test, ast.BoolOp):
            parts = [self._decided(v, trusted) for v in test.values]
            return any(parts) if isinstance(test.op, ast.And) else all(parts)
        if isinstance(test, ast.Compare):
            if (len(test.ops) == 1 and isinstance(test.ops[0], (ast.IsNot, ast.NotEq))
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value in (None, False)):
                return self._decided(test.left, trusted)
            return False
        if isinstance(test, ast.Name):
            return test.id in trusted
        if isinstance(test, (ast.Subscript, ast.Attribute)):
            return self._decided(test.value, trusted)
        if isinstance(test, ast.Call):
            return self._key(test.func) in self.decider_keys
        return False

    def _waits_for_a_drawn_tab(self, loop) -> bool:
        """A loop that ends in a failure when it runs out, every break of
        which is decided by a tab, through a name the loop binds only from a
        call that opened one and sent it to a page, or such a call itself."""
        if not any(isinstance(n, ast.Raise) or (isinstance(n, ast.Call) and _name(n) == "fail")
                   for stmt in loop.orelse for n in ast.walk(stmt)):
            return False
        body = ast.Module(body=loop.body, type_ignores=[])
        from_a_tab, stored = set(), {}
        for node in ast.walk(body):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                stored.setdefault(node.id, set()).add(id(node))
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and self._key(node.value.func) in self.decider_keys):
                from_a_tab |= _ids(node.targets)
        trusted = {name for name, ids in stored.items() if ids <= from_a_tab}
        decided, breaks = set(), set()
        for node in _own(loop.body):
            if isinstance(node, ast.Break):
                breaks.add(id(node))
            if isinstance(node, ast.If) and self._decided(node.test, trusted):
                decided |= {id(s) for s in node.body if isinstance(s, ast.Break)}
        return bool(breaks) and breaks <= decided

    def guarded(self, name, seen=()) -> bool:
        """Whether every browser the function starts is handed over only once
        a tab has drawn, by a loop of its own or in the function it calls."""
        fn = self.functions[name]
        launches = self._launches(name)
        waiting = [_ids(loop.body) for loop in ast.walk(fn)
                   if isinstance(loop, ast.For) and self._waits_for_a_drawn_tab(loop)]
        for key, node in launches:
            if any(id(node) in body for body in waiting):
                continue
            if key in self.functions and key not in seen and self.guarded(key, seen + (name,)):
                continue
            there = self._outside(key) if key else None
            if there and there[1] in there[0].starters and there[0].guarded(there[1]):
                continue
            return False
        return bool(launches)

    def handed_over(self) -> list:
        """The functions here that start a browser and that nothing else
        here calls, the fixtures and tests that hand one to an app."""
        used = {key for caller in self.functions for key, _ in self._reads[caller]
                if key in self.starters and key != caller}
        return sorted(name for name in self.starters if name not in used)

    def unguarded(self) -> list:
        out = ["%s line %d starts a browser outside any function" % (self.path.name, line)
               for line in self.loose]
        out += ["%s %s, line %d" % (self.path.name, name, self.functions[name].lineno)
                for name in self.handed_over() if not self.guarded(name)]
        return out


def only_tab(call) -> bool:
    return any(k.arg == "only_tab" and isinstance(k.value, ast.Constant) and k.value.value is True
               for k in call.keywords)


def first_tab_reads(app: Path) -> list:
    """Where the app, attached to a browser, works in the first tab it
    finds. A function that reads a context's pages[0] and opens a new tab
    of the same context picks the tab it works in, and it counts unless
    that read is only where the app is not attached, the else of an if on
    a name of its attached mode."""
    found = []
    for path in sorted(app.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "pages[0]" not in source:
            continue
        tree = ast.parse(source)
        up = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for fn in (n for n in ast.walk(tree) if isinstance(n, FUNCTION)):
            opened = {ast.dump(n.func.value) for n in ast.walk(fn) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Attribute) and n.func.attr == "new_page"}
            for read in ast.walk(fn):
                if (isinstance(read, ast.Subscript) and isinstance(read.value, ast.Attribute)
                        and read.value.attr == "pages" and isinstance(read.slice, ast.Constant)
                        and read.slice.value == 0 and ast.dump(read.value.value) in opened
                        and not _only_when_not_attached(read, up)):
                    found.append("%s line %d" % (path.name, read.lineno))
    return sorted(set(found))


def _names_the_attached_mode(test) -> bool:
    return any("cdp" in (n.value if isinstance(n, ast.Constant) and isinstance(n.value, str)
                         else getattr(n, "id", "") or getattr(n, "attr", "")).lower()
               for n in ast.walk(test))


def _only_when_not_attached(node, up) -> bool:
    child = node
    while child in up:
        parent = up[child]
        if isinstance(parent, (ast.If, ast.IfExp)) and _names_the_attached_mode(parent.test):
            negated = isinstance(parent.test, ast.UnaryOp) and isinstance(parent.test.op, ast.Not)
            body = parent.body if isinstance(parent.body, list) else [parent.body]
            orelse = parent.orelse if isinstance(parent.orelse, list) else [parent.orelse]
            if any(child is s for s in orelse):
                return not negated
            if any(child is s for s in body):
                return negated
        child = parent
    return False


HELPER = Module(TESTKIT)


def _imports(tree) -> set:
    """The last part of every name the module imports, or imports from."""
    out = set()
    for node in _module_level(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[-1] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out |= {a.name for a in node.names} | {(node.module or "").split(".")[-1]}
    return out


def read_all():
    """Each test module, read with testkit and the files beside it as what
    it can import."""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in files_to_read()}
    alone = {path: Module(path, tree=tree) for path, tree in trees.items()}
    out = []
    for path, tree in trees.items():
        others = {p.stem: m for p, m in alone.items() if p.parent == path.parent and p != path}
        others["testkit"] = HELPER
        if _imports(tree) & set(others):
            out.append(Module(path, others=others, tree=tree))
        else:
            out.append(alone[path])
    return out


MODULES = read_all()


def _rel(module) -> str:
    return module.path.relative_to(REPO).as_posix()


STARTING = {_rel(m): m for m in MODULES if m.starters or m.loose}
DRAWN = {_rel(m): m for m in MODULES if m.drawn_calls}
APPS = sorted(p for p in (REPO / "apps").iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
FIRST_TAB = {app.name: reads for app in APPS for reads in [first_tab_reads(app)] if reads}

# Every test file that started a browser for an app on 2026-10-03, with a
# fixture of its own or through testkit.drawn_browser.
KNOWN = {
    "apps/amazon/tests/test_a_list_that_never_came.py",
    "apps/amazon/tests/test_the_page_printed_is_the_purchase.py",
    "apps/bestbuy/tests/test_a_list_that_never_came.py",
    "apps/bestbuy/tests/test_signed_out_mid_run.py",
    "apps/costco/tests/test_a_list_that_never_came.py",
    "apps/ebay/tests/test_a_list_that_never_came.py",
    "apps/gap/tests/test_a_list_that_never_came.py",
    "apps/gap/tests/test_the_page_printed_is_the_purchase.py",
    "apps/github/tests/test_a_list_that_never_came.py",
    "apps/github/tests/test_signed_out_mid_run.py",
    "apps/github/tests/test_the_page_printed_is_the_purchase.py",
    "apps/homedepot/tests/test_a_list_that_never_came.py",
    "apps/lowes/tests/test_a_list_that_never_came.py",
    "apps/meijer/tests/test_the_page_printed_is_the_purchase.py",
    "apps/target/tests/test_a_receipt_control_it_could_not_read.py",
    "apps/target/tests/test_every_invoice_of_an_order.py",
    "apps/target/tests/test_the_list_already_open.py",
    "apps/target/tests/test_the_page_printed_is_the_purchase.py",
    "apps/walmart/tests/test_a_list_that_never_came.py",
    "apps/walmart/tests/test_signed_out_mid_run.py",
    "apps/walmart/tests/test_the_page_printed_is_the_purchase.py",
    "core/tests/test_a_printed_page_goes_back_to_the_screen.py",
}


def test_the_census_finds_every_test_that_starts_a_browser():
    """A file that stops being found has moved its browser somewhere this
    cannot see, and this says so rather than letting it drop out of the
    guard quietly."""
    assert KNOWN <= set(STARTING), sorted(KNOWN - set(STARTING))


@pytest.mark.parametrize("name", sorted(STARTING))
def test_a_browser_started_for_an_app_draws_a_page_first(name):
    assert STARTING[name].unguarded() == [], (
        "%s hands an app a browser before a tab of it has drawn a page. %s" % (name, HOW))


def test_the_shared_helper_is_held_to_the_same_check():
    """drawn_browser starts its browsers the way a fixture of its own does,
    so it is read the same way, and a helper that stopped waiting for its
    tab in either of its two ways fails here rather than in every fixture
    that trusts it."""
    assert "drawn_browser" in HELPER.handed_over()
    assert HELPER.unguarded() == []
    source = TESTKIT.read_text(encoding="utf-8")
    for waited in ("drew, did = _draws_alone(url, ready, tries)",
                   "drew, did = _draws(url, ready.address, tries)"):
        assert waited in source, "the helper changed, and so must this test"
        assert Module(TESTKIT, source.replace(waited, "drew, did = True, []")).unguarded(), waited


def test_the_apps_that_work_in_the_first_tab_they_find_are_known():
    """Target's page() takes the first tab when attached, where every other
    app opens a tab of its own. One that starts taking the first tab is
    named here, so that its tests are handed the drawn tab alone."""
    assert sorted(FIRST_TAB) == ["target"], FIRST_TAB


@pytest.mark.parametrize("name", sorted(n for n in DRAWN if n.split("/")[0] == "apps"
                                        and n.split("/")[1] in FIRST_TAB))
def test_an_app_that_works_in_the_first_tab_it_finds_is_handed_the_drawn_tab_alone(name):
    calls = DRAWN[name].drawn_calls
    assert all(only_tab(call) for call in calls), (
        "%s works in the first tab it finds, %s. Hand it the browser with "
        "testkit.drawn_browser(..., only_tab=True)" % (name.split("/")[1], FIRST_TAB[name.split("/")[1]]))


# Fixtures for the census itself. The first is the shape of the six page
# check fixtures of 2026-10-03.
STRAIGHT_OVER = '''
import subprocess
import pytest

@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    profile = tmp_path_factory.mktemp("attached-profile")
    proc = subprocess.Popen([browser_exe, "--headless=new", "--remote-debugging-port=0",
                             "--user-data-dir=%s" % profile, "about:blank"])
    yield "http://127.0.0.1:%s" % (profile / "DevToolsActivePort").read_text().split()[0]
    proc.kill()
'''

WAITS_FOR_A_TAB = '''
import subprocess
import pytest

ARGS = ["--headless=new", "--remote-debugging-port=0"]

def _start_browser(exe, profile):
    proc = subprocess.Popen([exe, *ARGS, "--user-data-dir=%s" % profile])
    return proc, "http://127.0.0.1:9"

def _draws(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.connect_over_cdp(url).contexts[0].new_page()
        page.goto("http://127.0.0.1:8/")
        return page.title() == "ready"

@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    for _start in range(3):
        proc, url = _start_browser(browser_exe, tmp_path_factory.mktemp("profile"))
        ready = _draws(url)
        if ready:
            break
        proc.kill()
    else:
        pytest.fail("no fresh browser drew a page")
    yield url
'''

ARGS_BESIDE = 'ARGS = ["--headless=new", "--remote-debugging-port=0"]\n'

SAMPLES = {
    "handed straight over": (STRAIGHT_OVER, ["attached"]),
    "waits for a tab that drew": (WAITS_FOR_A_TAB, []),
    "breaks once the port answers": (
        WAITS_FOR_A_TAB.replace("if ready:", "if url is not None:"), ["attached"]),
    "breaks on the port or the tab": (
        WAITS_FOR_A_TAB.replace("if ready:", "if url is not None or ready:"), ["attached"]),
    "breaks on a tab never sent to a page": (
        WAITS_FOR_A_TAB.replace('        page.goto("http://127.0.0.1:8/")\n', ""), ["attached"]),
    "takes the tab's word only sometimes": (
        WAITS_FOR_A_TAB.replace("ready = _draws(url)", "ready = _draws(url) if url else True"),
        ["attached"]),
    "starts a browser that opens its own tab": (
        WAITS_FOR_A_TAB.replace('    return proc, "http://127.0.0.1:9"',
                                '    page = proc.contexts[0].new_page()\n'
                                '    page.goto("http://127.0.0.1:8/")\n'
                                '    return proc, page')
        .replace("ready = _draws(url)\n        if ready:", "if url is not None:"), ["attached"]),
    "the argument two names away": (
        STRAIGHT_OVER.replace('"--remote-debugging-port=0",', "*ARGS,")
        .replace("import pytest\n", 'import pytest\nPORT = "--remote-debugging-port=0"\n'
                 'ARGS = [PORT]\n'), ["attached"]),
    "a command line in one string": (
        STRAIGHT_OVER.replace('"--headless=new", "--remote-debugging-port=0",',
                              '*"--headless=new --remote-debugging-port=0".split(),'), ["attached"]),
    "a fixture of a test class": ('''
import subprocess
import pytest

class TestPages:
    @pytest.fixture
    def attached(self, browser_exe, tmp_path_factory):
        profile = tmp_path_factory.mktemp("attached-profile")
        proc = subprocess.Popen([browser_exe, "--remote-debugging-port=0",
                                 "--user-data-dir=%s" % profile])
        yield "http://127.0.0.1:9"
        proc.kill()
''', ["TestPages.attached"]),
    "the argument from a file beside it": (
        STRAIGHT_OVER.replace('"--headless=new", "--remote-debugging-port=0",', "*ARGS,")
        .replace("import pytest\n", "import pytest\nfrom browser_args import ARGS\n"), ["attached"]),
    "testkit's own start, handed straight over": ('''
import pytest
from paperpull_core import testkit

@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    proc, url = testkit._start_fresh_browser(browser_exe, tmp_path_factory.mktemp("p"), ())
    yield url
    proc.kill()
''', ["attached"]),
    "drawn_browser with arguments of the module's own": ('''
import pytest
from paperpull_core import testkit
ARGS = ["--remote-debugging-port=0"]

@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("p"), args=ARGS) as url:
        yield url
''', []),
}


@pytest.mark.parametrize("sample", sorted(SAMPLES))
def test_the_census_tells_a_browser_that_waited_from_one_that_did_not(sample):
    source, flagged = SAMPLES[sample]
    others = {"testkit": HELPER, "browser_args": Module(Path("browser_args.py"), ARGS_BESIDE)}
    found = Module(Path("sample.py"), source, others=others).unguarded()
    assert [line.split(",")[0].split(" ", 1)[1] for line in found] == flagged, found
