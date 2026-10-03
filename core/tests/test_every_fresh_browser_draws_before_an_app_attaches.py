"""Every browser a test starts for an app to attach to has drawn a page
before the app attaches.

A browser that has only just started is not the one login.bat leaves open
at home. On CI a fresh Chrome's first navigation came back net::ERR_ABORTED
after about five seconds, which is how a browser answers when its network
service restarts under it, and about one fresh start in thirteen loses its
first tab. A fixture that hands such a browser straight to the app fails
on the app's very first goto. The GitHub, Walmart,
Best Buy and Target fixtures were guarded against it one by one on
2026-10-01, and six page check files added on 2026-10-03 came without the
guard. Target's failed on CI the same day, run 37123796050, with the abort
on its first goto.

So a test that starts a browser with a debugging port hands it over only
once a tab has drawn a page. testkit.drawn_browser does that in one place.
A fixture of its own does it the same way, starting the browser inside a
loop that ends in a failure when no browser gets there, and leaving the
loop only by a break that a tab it opened decided. A test is found here by
what it does, giving a browser the argument that opens a debugging port,
directly or through a function of its module, and is held to one of the
two. This file names that argument and starts no browser, so it is left
out.

It needs no browser.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TESTKIT = REPO / "core" / "paperpull_core" / "testkit.py"

# The argument a browser is started with for an app to attach to.
PORT_FLAG = "--remote-debugging-port"

HOW = ("Start it with testkit.drawn_browser, and with only_tab=True when the app works "
       "in the first tab it finds rather than a tab of its own.")


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
    functions it defines, each of which hides a function of the module."""
    out = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    out |= {n.name for n in ast.walk(fn)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn}
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
            if not isinstance(child, (ast.For, ast.While, ast.FunctionDef,
                                      ast.AsyncFunctionDef, ast.Lambda)):
                stack.append(child)


def _port_flags(tree) -> list:
    """Every string that opens a debugging port, left out where it is only
    looked for, in an assert or a comparison."""
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and n.value.startswith(PORT_FLAG)]
    if not found:
        return []
    looked_for = _ids(n for n in ast.walk(tree) if isinstance(n, (ast.Assert, ast.Compare)))
    return [n for n in found if id(n) not in looked_for]


def _names_the_helper(tree) -> bool:
    return any((isinstance(n, ast.Name) and n.id == "drawn_browser")
               or (isinstance(n, ast.Attribute) and n.attr == "drawn_browser")
               for n in ast.walk(tree))


class Module:
    """One test module's functions, which of them start a browser, and
    which open a tab in one."""

    def __init__(self, path: Path, source: str = None):
        self.path = path
        self.tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"))
        self.functions = {fn.name: fn for fn in self.tree.body
                          if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))}
        flags = _port_flags(self.tree)
        self.names_the_helper = _names_the_helper(self.tree)
        self.flag_names, self.loose, self.starters, self.tab_openers = set(), [], set(), set()
        self._reads, self._flags_in = {}, {}
        if not flags:
            # Nothing here starts a browser, so there is nothing to follow.
            return
        # What each function reads by name, less the names it binds itself.
        # A test's parameter named after a fixture is the fixture's value,
        # not the function.
        for name, fn in self.functions.items():
            hidden = _locals(fn)
            self._reads[name] = [n for n in ast.walk(fn) if isinstance(n, ast.Name)
                                 and isinstance(n.ctx, ast.Load) and n.id not in hidden]
        inside = _ids(self.functions.values())
        # The argument kept in a name of the module, to be handed on by the
        # functions that read it, and anything else outside a function,
        # which starts a browser at import and can wait for nothing.
        for stmt in self.tree.body:
            under = _ids([stmt])
            held = [n for n in flags if id(n) in under and id(n) not in inside]
            if not held:
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                self.flag_names |= {t.id for target in targets for t in ast.walk(target)
                                    if isinstance(t, ast.Name)}
            else:
                self.loose += [n.lineno for n in held]
        flag_ids = {id(f) for f in flags}
        self._flags_in = {name: [n for n in ast.walk(fn) if id(n) in flag_ids]
                          for name, fn in self.functions.items()}
        self.starters = self._closure({name for name in self.functions if self._own_flags(name)})
        self.tab_openers = self._closure({
            name for name, fn in self.functions.items()
            if any((isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "new_page")
                   or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and "/json/new" in n.value)
                   for n in ast.walk(fn))})

    def _own_flags(self, name) -> list:
        return self._flags_in.get(name, []) + [n for n in self._reads.get(name, [])
                                               if n.id in self.flag_names]

    def _uses(self, name, names) -> list:
        """Each place the function names one of these functions, called or
        handed on."""
        return [n for n in self._reads.get(name, []) if n.id in names]

    def _closure(self, names) -> set:
        found = set(names)
        while True:
            more = {name for name in self.functions if name not in found and self._uses(name, found)}
            if not more:
                return found
            found |= more

    def _launches(self, name) -> list:
        """Where the function starts a browser, by giving it the argument
        itself or through a function of this module that does."""
        return self._own_flags(name) + self._uses(name, self.starters - {name})

    def _waits_for_a_drawn_tab(self, loop) -> bool:
        """A loop that ends in a failure when it runs out, and that is left
        by a break decided by a tab it opened, a name bound in the loop from
        a call that opens a tab, or such a call itself."""
        if not any(isinstance(n, ast.Raise) or (isinstance(n, ast.Call) and _name(n) == "fail")
                   for stmt in loop.orelse for n in ast.walk(stmt)):
            return False
        bound = set()
        for node in ast.walk(ast.Module(body=loop.body, type_ignores=[])):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(c, ast.Call) and _name(c) in self.tab_openers
                            for c in ast.walk(node.value))):
                bound |= {t.id for target in node.targets for t in ast.walk(target)
                          if isinstance(t, ast.Name)}
        for node in _own(loop.body):
            if isinstance(node, ast.If) and any(isinstance(s, ast.Break) for s in node.body):
                read = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                if read & (bound | self.tab_openers):
                    return True
        return False

    def guarded(self, name, seen=()) -> bool:
        """Whether every browser the function starts is handed over only once
        a tab has drawn, by a loop of its own or in the function it calls."""
        fn = self.functions[name]
        launches = self._launches(name)
        waiting = [_ids(loop.body) for loop in ast.walk(fn)
                   if isinstance(loop, ast.For) and self._waits_for_a_drawn_tab(loop)]
        for launch in launches:
            if any(id(launch) in body for body in waiting):
                continue
            if (isinstance(launch, ast.Name) and launch.id in self.starters
                    and launch.id not in seen and self.guarded(launch.id, seen + (name,))):
                continue
            return False
        return bool(launches)

    def handed_over(self) -> list:
        """The functions here that start a browser and that nothing else
        here calls, the fixtures and tests that hand one to an app."""
        used = {n.id for caller in self.functions
                for n in self._uses(caller, self.starters - {caller})}
        return sorted(name for name in self.starters if name not in used)

    def unguarded(self) -> list:
        out = ["%s line %d starts a browser outside any function" % (self.path.name, line)
               for line in self.loose]
        out += ["%s %s, line %d" % (self.path.name, name, self.functions[name].lineno)
                for name in self.handed_over() if not self.guarded(name)]
        return out

    def drawn_browser_users(self) -> list:
        if not self.names_the_helper:
            return []
        return sorted(name for name, fn in self.functions.items()
                      if any(isinstance(n, ast.withitem) and isinstance(n.context_expr, ast.Call)
                             and _name(n.context_expr) == "drawn_browser"
                             for n in ast.walk(fn)))


MODULES = [Module(path) for path in files_to_read()]


def _rel(module) -> str:
    return module.path.relative_to(REPO).as_posix()


STARTING = {_rel(m): m for m in MODULES if m.starters or m.loose}
DRAWN = {_rel(m): m for m in MODULES if m.drawn_browser_users()}

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
    found = set(STARTING) | set(DRAWN)
    assert KNOWN <= found, sorted(KNOWN - found)


@pytest.mark.parametrize("name", sorted(STARTING))
def test_a_browser_started_for_an_app_draws_a_page_first(name):
    assert STARTING[name].unguarded() == [], (
        "%s hands an app a browser before a tab of it has drawn a page. %s" % (name, HOW))


def test_the_shared_helper_is_held_to_the_same_check():
    """drawn_browser starts its browsers the way a fixture of its own does,
    so it is read the same way, and a helper that stopped waiting for its
    tab would fail here rather than in every fixture that trusts it."""
    helper = Module(TESTKIT)
    assert "drawn_browser" in helper.handed_over()
    assert helper.unguarded() == []


# The shape of the six page check fixtures of 2026-10-03, and two that
# loop. One waits for a tab it opened, and one only for a debugging port.
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

ONLY_A_PORT = WAITS_FOR_A_TAB.replace("if ready:", "if url is not None:")


def test_the_census_tells_a_browser_handed_straight_over_from_one_that_waited():
    assert [u.split(",")[0] for u in Module(Path("old.py"), STRAIGHT_OVER).unguarded()] \
        == ["old.py attached"]
    assert Module(Path("waits.py"), WAITS_FOR_A_TAB).unguarded() == []
    assert [u.split(",")[0] for u in Module(Path("port.py"), ONLY_A_PORT).unguarded()] \
        == ["port.py attached"], "a debugging port that answers is not a page that drew"
