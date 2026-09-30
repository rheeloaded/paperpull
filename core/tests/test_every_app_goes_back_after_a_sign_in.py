"""After signing in again at a console, a run goes back to the page it had open.

Every app has a session check. When the site has signed the person out and
there is somebody at the console, it asks them to sign in again, and then
it opens the app's list, the order list or the documents page, because
that is a page it knows how to open. Under the panel there is nobody to
ask and the run stops there instead.

The list is the wrong page for most of the places the check is called
from. Walmart's run opened a purchase's details page, checked, and read
whatever was in front of it, which after a sign-in was the order list. The
purchase took another order's date and the list's address, and the list
itself was printed and filed under the purchase's name. The provider's
name is on the list, so the check on the saved file passed it, and the
purchase was marked as downloaded for good. Ten receipt apps opened a
purchase that way. GitHub and Meijer open a receipt's own page the same
way, and GitHub's payment history, which has amounts and the word receipt
on it, passed for the receipt and was printed as it. Amazon, eBay,
GitHub, Meijer and Lowe's walked their history a year or a page at a time
and would read the first page of the list as the page they had asked for,
then stop, as though the history ended there. Robinhood opened the section
page a statement lives on and would have looked for it on another.

So the check now says whether it moved the page, and a caller that had
opened somewhere in particular opens it again for as long as the check
had to. Nothing here finds an app by the name of anything. The check is
the method that asks the person and then moves the page, and the place it
was called from is whatever the run opened last before calling it.
"""
import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")))

# What a page is told to do that takes it somewhere.
PAGE_MOVES = {"goto", "reload", "go_back", "go_forward"}
# The question put to somebody at the console mid-run. cmd_login waits with
# pause_for_sign_in and a run's YES with ask, and neither is a session check.
ASKS = {"ask_or_none"}


def _parse(path: Path):
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def _calls(node) -> list:
    return sorted((n for n in ast.walk(node) if isinstance(n, ast.Call)),
                  key=lambda c: (c.lineno, c.col_offset))


def _name(call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    return f.id if isinstance(f, ast.Name) else ""


def _owner(call) -> str:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id
    return ""


def _moving_site_functions(tree) -> set:
    """The site module's functions that move the page, themselves or
    through another of its functions."""
    fns = {n.name: n for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    moves, grew = set(), True
    while grew:
        grew = False
        for name, fn in fns.items():
            if name not in moves and any(
                    _name(c) in PAGE_MOVES
                    or (isinstance(c.func, ast.Name) and c.func.id in moves)
                    for c in _calls(fn)):
                moves.add(name)
                grew = True
    return moves


class Census:
    """One app, read for its session check and every place it is called."""

    def __init__(self, entry: Path):
        self.entry = entry
        self.app = entry.parent.name
        tree = _parse(entry)
        site = entry.parent / ("%s_site.py" % self.app)
        site_tree = _parse(site) if site.exists() else ast.Module(body=[], type_ignores=[])
        self.site_moves = _moving_site_functions(site_tree)
        self.site_defs = {n.name: n for n in site_tree.body if isinstance(n, ast.FunctionDef)}
        self.methods = {fn.name: fn for cls in tree.body if isinstance(cls, ast.ClassDef)
                        for fn in cls.body if isinstance(fn, ast.FunctionDef)}
        self.class_of = {fn.name: cls.name for cls in tree.body if isinstance(cls, ast.ClassDef)
                         for fn in cls.body if isinstance(fn, ast.FunctionDef)}
        self.self_moves, grew = set(), True
        while grew:
            grew = False
            for name, fn in self.methods.items():
                if name not in self.self_moves and any(self.moves(c) for c in _calls(fn)):
                    self.self_moves.add(name)
                    grew = True
        # The check is the method that asks and then moves the page itself.
        # Where it moves it is the last move after the first question. A
        # method that asks and then calls the check, as the order list's
        # opener does in two apps, is a caller of it, not another check.
        self.landing = {}
        for name, fn in self.methods.items():
            calls = _calls(fn)
            asked = [i for i, c in enumerate(calls) if _name(c) in ASKS]
            moved = [c for c in calls[asked[0]:]
                     if _name(c) in PAGE_MOVES
                     or (_owner(c) == "site" and _name(c) in self.site_moves)] if asked else []
            if moved:
                self.landing[name] = moved[-1]

    def moves(self, call) -> bool:
        name, owner = _name(call), _owner(call)
        return (name in PAGE_MOVES
                or (owner == "site" and name in self.site_moves)
                or (owner == "self" and name in getattr(self, "self_moves", ())))

    def is_check(self, call) -> bool:
        return _owner(call) == "self" and _name(call) in self.landing

    def places(self):
        """Every call to the check, with the statement it sits in, the
        last thing the run opened before it, and the parent map to walk."""
        for name, fn in self.methods.items():
            if name in self.landing:
                continue
            parent = {child: node for node in ast.walk(fn)
                      for child in ast.iter_child_nodes(node)}
            for call in _calls(fn):
                if not self.is_check(call):
                    continue
                stmt = call
                while not isinstance(stmt, ast.stmt):
                    stmt = parent[stmt]
                yield name, call, stmt, self._opened_before(stmt, parent), parent

    def _opening(self, node) -> list:
        return [c for c in _calls(node) if self.moves(c) and not self.is_check(c)]

    def _opened_before(self, stmt, parent):
        """The last call that moved the page before this statement runs,
        walking back through the statements before it and out through the
        ones around it."""
        node = stmt
        while True:
            par = parent.get(node)
            if par is None:
                return None
            before = []
            for field in ("body", "orelse", "finalbody"):
                block = getattr(par, field, None)
                if isinstance(block, list) and node in block:
                    before = block[:block.index(node)]
            if isinstance(par, ast.Try) and node in par.handlers:
                # a handler runs after part of the try body has run
                before = par.body
            for prev in reversed(before):
                found = self._opening(prev)
                if found:
                    return found[-1]
            head = []
            if isinstance(par, (ast.If, ast.While)):
                head = [par.test]
            elif isinstance(par, (ast.For, ast.AsyncFor)):
                head = [par.iter]
            elif isinstance(par, (ast.With, ast.AsyncWith)):
                head = [item.context_expr for item in par.items]
            found = [c for h in head for c in self._opening(h)]
            if found:
                return found[-1]
            if isinstance(par, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return None
            node = par


def _as_the_check_lands(census, opened, check) -> bool:
    """Opened by the very function the check goes back to, with nothing
    passed that is not that function's own default, so the page is the
    one the check leaves it on anyway. eBay opens its unfiltered history
    with an explicit None, and Lowe's its first page with an explicit 1."""
    landing = census.landing.get(_name(check))
    if landing is None or _owner(opened) != "site" or _name(opened) != _name(landing):
        return False
    fn = census.site_defs.get(_name(opened))
    if fn is None:
        return False
    params = [a.arg for a in fn.args.args]
    defaults = dict(zip(params[len(params) - len(fn.args.defaults):], fn.args.defaults))
    given = dict(zip(params[1:], opened.args[1:]))
    given.update({k.arg: k.value for k in opened.keywords})
    return all(isinstance(v, ast.Constant) and isinstance(defaults.get(k), ast.Constant)
               and v.value == defaults[k].value for k, v in given.items())


def _somewhere_in_particular(census, opened, check) -> bool:
    """Opened with anything more than the page itself, an order, an
    address, a year or a page number, rather than the list a sign-in goes
    back to. A page told to go somewhere always is."""
    if _name(opened) in PAGE_MOVES:
        return True
    page = check.args[0].id if check.args and isinstance(check.args[0], ast.Name) else "page"
    only_the_page = (len(opened.args) == 1 and isinstance(opened.args[0], ast.Name)
                     and opened.args[0].id == page and not opened.keywords)
    return not only_the_page and not _as_the_check_lands(census, opened, check)


def _needs_no_answer(check, stmt, opened, parent) -> bool:
    """Whatever the check did, nothing is read from the page it left,
    because the page is opened again at once with the very call that
    opened it.

    Going around a loop to its next item after a discarded check is not
    enough. Apple Card did that with a section that would not open after
    a sign-in, and the section was left out of the run without a word."""
    if not (isinstance(stmt, ast.Expr) and stmt.value is check):
        return False
    after = _next_statement(stmt, parent)
    if after is None:
        return False
    return any(ast.dump(c) == ast.dump(opened) for c in _calls(after))


def _next_statement(stmt, parent):
    """The statement that runs after this one when nothing is raised,
    out through the end of an if, a with or a try into what follows it.
    None at the end of a loop's body or of the function."""
    node = stmt
    while True:
        par = parent.get(node)
        if par is None:
            return None
        if isinstance(node, ast.ExceptHandler):
            node = par
            continue
        for field in ("body", "orelse", "finalbody"):
            block = getattr(par, field, None)
            if isinstance(block, list) and node in block:
                i = block.index(node)
                if i + 1 < len(block):
                    return block[i + 1]
        if not isinstance(par, (ast.If, ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler)):
            return None
        node = par


def _goes_back(check, stmt, opened) -> bool:
    """The page is opened again with the very call that opened it, for as
    long as the check says it moved it."""
    return (isinstance(stmt, ast.While) and stmt.test is check
            and any(ast.dump(c) == ast.dump(opened) for s in stmt.body for c in _calls(s)))


CENSUS = [Census(e) for e in ENTRIES]


def _particular(census):
    """The places the check is called after the run opened somewhere in
    particular, and something may be read from the page after it."""
    return [(name, check, stmt, opened, parent)
            for name, check, stmt, opened, parent in census.places()
            if opened is not None and _somewhere_in_particular(census, opened, check)
            and not _needs_no_answer(check, stmt, opened, parent)]


# The apps whose check has to say whether it moved the page.
NEEDING_AN_ANSWER = [c for c in CENSUS if _particular(c)]


def test_the_census_finds_the_checks_it_is_about():
    """Not vacuous. Every app that asks at a console mid-run is found by
    what its check does, and the places it is called from after opening
    somewhere in particular are the ones this was written about."""
    with_a_check = [c.app for c in CENSUS if c.landing]
    assert len(with_a_check) >= 55, with_a_check
    assert all(list(c.landing) == ["check_session"] for c in CENSUS if c.landing), \
        {c.app: list(c.landing) for c in CENSUS if c.landing}
    names = {c.app for c in NEEDING_AN_ANSWER}
    for app in ("walmart", "bestbuy", "amazon", "costco", "ebay", "gap", "github",
                "homedepot", "kroger", "lowes", "meijer", "target", "robinhood"):
        assert app in names, (app, sorted(names))


@pytest.mark.parametrize("census", NEEDING_AN_ANSWER, ids=lambda c: c.app)
def test_a_page_opened_before_the_check_is_opened_again_after_a_sign_in(census):
    left = []
    for name, check, stmt, opened, parent in _particular(census):
        if not _goes_back(check, stmt, opened):
            left.append("in %s at line %d after %s" % (
                name, check.lineno, ast.unparse(opened)))
    assert not left, (
        "%s checks the session after opening somewhere in particular and then "
        "reads what is in front of it, which after a sign-in at the console is "
        "the list the check opened. It does so %s" % (census.app, ", and ".join(left)))


def _entry_module(census):
    for name in [m for m in list(sys.modules)
                 if m == "storage" or m.endswith(("_site", "_docs", "_receipts"))]:
        del sys.modules[name]
    sys.path.insert(0, str(census.entry.parent))
    try:
        return importlib.import_module(census.entry.stem)
    finally:
        sys.path.pop(0)


@pytest.fixture()
def check(request, monkeypatch):
    """The app's own check, called on a page that is not there, with the
    site's answers and the person at the console played here."""
    census = request.param
    mod = _entry_module(census)
    site = mod.site
    from paperpull_core import browser as browser_launcher
    # The check the places above call, found by what it does, and where it
    # takes the page after a sign-in.
    name = _name(_particular(census)[0][1])
    landing = _name(census.landing[name])
    world = {"challenge": None, "signed_out": False, "answer": "", "moved": 0}

    def moved(*a, **k):
        world["moved"] += 1
        world["signed_out"] = False

    monkeypatch.setattr(site, "detect_security_challenge", lambda page: world["challenge"])
    monkeypatch.setattr(site, "looks_signed_out", lambda page: world["signed_out"])
    monkeypatch.setattr(site, landing, moved)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: world["answer"])
    method = getattr(getattr(mod, census.class_of[name]), name)
    app = MagicMock()

    def run():
        return method(app, MagicMock())
    return world, run


def _each(fixture):
    return pytest.mark.parametrize(fixture, NEEDING_AN_ANSWER, indirect=True,
                                   ids=lambda c: c.app)


@_each("check")
def test_the_check_says_it_moved_the_page_after_a_sign_in(check):
    world, run = check
    world["signed_out"] = True
    assert run() is True
    assert world["moved"] == 1


@_each("check")
def test_the_check_says_nothing_moved_when_the_session_is_fine(check):
    world, run = check
    assert run() is False
    assert world["moved"] == 0


@_each("check")
def test_a_challenge_answered_at_the_console_does_not_open_the_page_again(check):
    """The question about a bot check does not move the page, and a word on
    an ordinary page that looks like one is asked about once, as before,
    rather than again every time the page is opened."""
    world, run = check
    world["challenge"] = "Security challenge detected: 'robot or human'"
    assert run() is False
    assert world["moved"] == 0


@_each("check")
def test_with_nobody_to_ask_the_run_still_stops(check):
    world, run = check
    world["signed_out"], world["answer"] = True, None
    with pytest.raises(SystemExit) as stopped:
        run()
    assert stopped.value.code == 0
    assert world["moved"] == 0
