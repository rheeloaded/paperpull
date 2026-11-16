"""Every Diagnose lists with the settings its own Discover lists with.

A Diagnose is the support report. It lists the documents a run would list
and writes what it found, so that a run which fails can be repaired from a
report made on the same account. Several Diagnoses called the listing with
the page alone, where Discover hands it the config and the years the run
cares about. Fidelity's asked for statements and trade confirmations where
a run asks for tax forms too (#223), NetBenefits' made quarterly statements
for a person whose run asks monthly ones, and Invest529, Amazon Visa, DKB,
1822direkt and Renault Bank listed every kind whatever document_types held.
A report then showed nothing wrong where the run failed.

This reads the shape of each app's own script. The Discover side is
cmd_discover and every method of the script it reaches through self, and
the Diagnose side is what cmd_diagnose reaches that Discover does not, so
a helper both share is one call and agrees with itself. A call of the site
module made on both sides is compared, whatever name the module is
imported as and for a function imported from it by name too. Every
argument Discover passes it that carries the run's settings has to be
passed by Diagnose too, by the same keyword, in the same place or in the
same ** spread, written as Discover writes it once each local is read
through the one value it was set from. So config=None, keep=None and a keep
built from anything but the run's own command line and config are refused.

A value carries settings when it reads self.config or self.args, directly,
through a local the same function set from such a value, plainly or as a
part of several set at once, or through a method of the script that reads
them, as IRS asks whether notices are in scope. Anything else Discover
hands the listing, a list it fills, a trace, a count of rounds, a download
folder, is the run's own and not compared. So is a year or a page a loop
walks over, a place in the run's walk that a Diagnose looking at one place
does not leave out, and so is the page. A value the script keeps on itself,
self.floor say, is not followed, since most of those are lists a listing
fills.

A report can list through a function its run reaches only inside the site
module, as Interactive Brokers' reads the months and Vanguard's the
statements its run's listing reads through. So every site function the
report alone calls is read by its signature too. One that takes keep or
config has to be handed the value every app hands it,
scope.period_filter(self.args, self.config) or self.config, and one that
takes floor, limit_date or notices has to be handed a value that carries
settings.

What it cannot see. A report that lists through a function taking none of
those names, whose run calls another, is compared with nothing, Bank of
America's, Chase's, U.S. Bank's, Alpaca's, Ally's, Target's and Walmart's
among them. Nor does it follow settings handed to a helper both sides
share as its arguments, a loop over values of the config, or a method that
reads the settings only through another method. The page is the one place
it knows of, and none of these happens in an app today.

That reading is held to what the app does as well. Each app the census
compares has its Diagnose run here through main(), with no browser, a page
that holds nothing and every site call it makes answered as an empty page
would. The listing records what it was handed, and each setting has to be
what Discover's own expression makes of the same config and command line,
unscoped, for one year, from a start date in the config and with one kind
of document kept. Every value here is made up.

An exemption names the app, the listing and the argument, and says why.
Each holds only while its reason does, and one that no longer finds its
gap fails, so the list only ever shrinks.
"""
import ast
import copy
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import scope as run_scope

REPO =Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in REPO.glob("apps/*/*.py")
                 if p.name.endswith(("_docs.py", "_receipts.py")) and not p.name.startswith("."))

SETTINGS = ("config", "args")
# The script's own methods that answer the browser page. Each reads the
# config to reach the browser, but the page is where a listing reads, not
# what it is asked for.
PLACES = ("page",)
SPREAD = "**"
# The names a site function takes the run's settings by, with how a run
# writes the value where every app writes it alike.
TAKEN = {"keep": "scope.period_filter(self.args, self.config)", "config": "self.config",
         "floor": None, "limit_date": None, "notices": None}


# ---------------------------------------------------------------------------
# Reading a script
# ---------------------------------------------------------------------------

def _functions(tree):
    """Every function of the script by name, methods and module functions
    alike. A name defined twice keeps every definition."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, []).append(node)
    return found


def _site_names(tree):
    """The names the site module is imported as, `import x_site as site`,
    and each function imported from it by name, with the name it has
    there."""
    modules, functions = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("_site"):
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith("_site"):
            for alias in node.names:
                functions[alias.asname or alias.name] = alias.name
    return modules, functions


def _self_calls(fn):
    """The names of the script's own methods this function calls through
    self, self.name(...)."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"):
            yield node.func.attr


def _reach(functions, start):
    """The names of the functions `start` reaches through self, itself
    included."""
    seen, todo = set(), [start]
    while todo:
        name = todo.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for fn in functions[name]:
            todo.extend(_self_calls(fn))
    return seen


def _reads_settings_directly(node):
    return any(isinstance(n, ast.Attribute) and n.attr in SETTINGS
               and isinstance(n.value, ast.Name) and n.value.id == "self"
               for n in ast.walk(node))


def _parts(target, value):
    """Each name a target sets with the value it gets. The parts of a tuple
    or list target take the parts of a value of the same length, and
    otherwise the whole value."""
    if isinstance(target, (ast.Tuple, ast.List)):
        parts = (value.elts if isinstance(value, (ast.Tuple, ast.List))
                 and len(value.elts) == len(target.elts) else None)
        for i, part in enumerate(target.elts):
            yield from _parts(part, parts[i] if parts else value)
    elif isinstance(target, ast.Starred):
        yield from _parts(target.value, value)
    elif isinstance(target, ast.Name):
        yield target.id, value


def _assigned(fn, name):
    """Each value the function gives the local `name`."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for part, value in _parts(target, node.value):
                    if part == name:
                        yield value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(node.target, ast.Name) and node.target.id == name \
                    and node.value is not None:
                yield node.value
        elif isinstance(node, ast.NamedExpr) and node.target.id == name:
            yield node.value


def carries_settings(expr, fn, functions, _seen=None) -> bool:
    """Whether a value reads the run's settings, directly, through a local
    set from them, or through a method of the script that reads them."""
    seen = set() if _seen is None else _seen
    if _reads_settings_directly(expr):
        return True
    for node in ast.walk(expr):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) \
                and ("name", id(fn), node.id) not in seen:
            seen.add(("name", id(fn), node.id))
            if any(carries_settings(v, fn, functions, seen) for v in _assigned(fn, node.id)):
                return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "self"
                and node.func.attr not in PLACES and ("method", node.func.attr) not in seen):
            seen.add(("method", node.func.attr))
            if any(_reads_settings_directly(m) for m in functions.get(node.func.attr, [])):
                return True
    return False


class _Unreadable(Exception):
    pass


class _Locals(ast.NodeTransformer):
    """Puts in place of each local the one value the function set it from."""

    def __init__(self, fn, depth):
        self.fn, self.depth = fn, depth

    def visit_Name(self, node):
        if not isinstance(node.ctx, ast.Load):
            return node
        values = list(_assigned(self.fn, node.id))
        if not values:
            return node
        if len(values) > 1 or self.depth > 8:
            raise _Unreadable(node.id)
        return _Locals(self.fn, self.depth + 1).visit(copy.deepcopy(values[0]))


def _resolved(expr, fn):
    """The expression with each local read through the one value the
    function set it from, or None when a local was set more than once, so
    what it holds cannot be told from its text."""
    try:
        return _Locals(fn, 0).visit(copy.deepcopy(expr))
    except _Unreadable:
        return None


def _site_calls(fn, names):
    """Each call of the site module in the function, with the name of the
    site function it calls."""
    modules, imported = names
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id in modules):
            yield node, node.func.attr
        elif isinstance(node.func, ast.Name) and node.func.id in imported:
            yield node, imported[node.func.id]


def _parameters(site_tree, name):
    """The positional parameter names of the site module's function, or
    None when it is not defined there."""
    for node in site_tree.body if site_tree else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return [a.arg for a in node.args.posonlyargs + node.args.args]
    return None


def _site_tree(entry: Path, tree):
    """The site module's own tree, found beside the script by the name it
    is imported by, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith("_site"):
                    path = entry.parent / (alias.name + ".py")
                    if path.exists():
                        return ast.parse(path.read_text(encoding="utf-8"))
    return None


def _settings_wanted(call, fn, functions, params):
    """What a Discover call hands the listing that carries settings, each
    as (keyword name, position or None, the expression)."""
    for kw in call.keywords:
        if carries_settings(kw.value, fn, functions):
            if kw.arg is None:
                yield SPREAD, None, kw.value
            else:
                pos = params.index(kw.arg) if params and kw.arg in params else None
                yield kw.arg, pos, kw.value
    for i, arg in enumerate(call.args):
        if isinstance(arg, ast.Starred):
            break
        if carries_settings(arg, fn, functions):
            yield (params[i] if params and i < len(params) else "#%d" % i), i, arg


def _handed(call, name, pos):
    """The expression a call hands for that argument, or None."""
    for kw in call.keywords:
        if (kw.arg is None and name == SPREAD) or (kw.arg is not None and kw.arg == name):
            return kw.value
    if pos is not None and pos < len(call.args) and not any(
            isinstance(a, ast.Starred) for a in call.args[:pos + 1]):
        return call.args[pos]
    return None


def _given(dcall, dfn, name, pos, rexpr, rfn, functions):
    """Whether a Diagnose call hands the listing that setting as Discover
    writes it, or, where Discover's local was set more than once, with a
    value that carries settings."""
    dexpr = _handed(dcall, name, pos)
    if dexpr is None or not carries_settings(dexpr, dfn, functions):
        return False
    want = _resolved(rexpr, rfn)
    if want is None:
        return True
    got = _resolved(dexpr, dfn)
    return got is not None and ast.dump(got) == ast.dump(want)


def wanted_in(source: str, entry: Path = None, site_source: str = None):
    """Each setting Discover hands a listing that Diagnose calls too, as
    (Diagnose call, its function, listing, setting name, place, Discover's
    expression, Discover call, its function), with the functions of the
    script by name."""
    tree = ast.parse(source)
    functions = _functions(tree)
    names = _site_names(tree)
    if site_source is not None:
        site_tree = ast.parse(site_source)
    else:
        site_tree = _site_tree(entry, tree) if entry else None
    discover = _reach(functions, "cmd_discover")
    diagnose = _reach(functions, "cmd_diagnose") - discover
    run_calls = [(fn, c, listing) for name in sorted(discover) for fn in functions[name]
                 for c, listing in _site_calls(fn, names)]
    found = []
    for dname in sorted(diagnose):
        for dfn in functions[dname]:
            for dcall, listing in _site_calls(dfn, names):
                params = _parameters(site_tree, listing)
                for rfn, rcall, rlisting in run_calls:
                    if rlisting != listing:
                        continue
                    for name, pos, rexpr in _settings_wanted(rcall, rfn, functions, params):
                        found.append((dcall, dfn, listing, name, pos, rexpr, rcall, rfn))
    return found, functions


def gaps_in(source: str, entry: Path = None, site_source: str = None):
    """Each (listing, argument, Diagnose line, Discover line) where Diagnose
    leaves out a setting Discover passes, and the number of listing calls
    compared that carry a setting on Discover's side."""
    found, functions = wanted_in(source, entry, site_source)
    gaps = [(listing, name, dcall.lineno, rcall.lineno)
            for dcall, dfn, listing, name, pos, rexpr, rcall, rfn in found
            if not _given(dcall, dfn, name, pos, rexpr, rfn, functions)]
    compared = len({(id(f[0]), id(f[6])) for f in found})
    return sorted(set(gaps)), compared


def _site_signature(site_tree, name):
    """(positional parameter names, every parameter name) of the site
    module's function, or None when it is not defined there."""
    for node in site_tree.body if site_tree else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            positional = [a.arg for a in node.args.posonlyargs + node.args.args]
            return positional, positional + [a.arg for a in node.args.kwonlyargs]
    return None


def taken_in(source: str, entry: Path = None, site_source: str = None):
    """Each setting a site function takes by the name the run hands it
    under, called on the Diagnose side only, as (Diagnose call, its
    function, listing, setting name, place), with the functions of the
    script by name. This reaches a report that lists through another
    function than its run does, as Interactive Brokers' reads the months
    its run's listing reads through."""
    tree = ast.parse(source)
    functions = _functions(tree)
    names = _site_names(tree)
    if site_source is not None:
        site_tree = ast.parse(site_source)
    else:
        site_tree = _site_tree(entry, tree) if entry else None
    diagnose = _reach(functions, "cmd_diagnose") - _reach(functions, "cmd_discover")
    found = []
    for dname in sorted(diagnose):
        for dfn in functions[dname]:
            for dcall, listing in _site_calls(dfn, names):
                signature = _site_signature(site_tree, listing)
                if not signature:
                    continue
                positional, every = signature
                for name in TAKEN:
                    if name in every:
                        pos = positional.index(name) if name in positional else None
                        found.append((dcall, dfn, listing, name, pos))
    return found, functions


def _taken_given(dcall, dfn, name, pos, functions) -> bool:
    dexpr = _handed(dcall, name, pos)
    if dexpr is None or not carries_settings(dexpr, dfn, functions):
        return False
    if TAKEN[name] is None:
        return True
    got = _resolved(dexpr, dfn)
    return got is not None and ast.dump(got) == ast.dump(ast.parse(TAKEN[name], mode="eval").body)


def taken_gaps_in(source: str, entry: Path = None, site_source: str = None):
    """Each (listing, argument, Diagnose line) where a site function the
    report alone calls takes a setting it is not handed as a run hands it."""
    found, functions = taken_in(source, entry, site_source)
    return sorted({(listing, name, dcall.lineno) for dcall, dfn, listing, name, pos in found
                   if not _taken_given(dcall, dfn, name, pos, functions)})


def gaps_of(entry: Path):
    return gaps_in(entry.read_text(encoding="utf-8"), entry)


def all_gaps_of(entry: Path):
    """Every (listing, argument, Diagnose line) either reading finds."""
    source = entry.read_text(encoding="utf-8")
    shared = {(listing, name, d) for listing, name, d, _ in gaps_in(source, entry)[0]}
    return sorted(shared | set(taken_gaps_in(source, entry)))


def shared_listings(entry: Path):
    """The site functions both sides call, settings or not."""
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    functions, names = _functions(tree), _site_names(tree)
    discover = _reach(functions, "cmd_discover")
    diagnose = _reach(functions, "cmd_diagnose") - discover
    side = lambda reached: {listing for n in reached for fn in functions[n]  # noqa: E731
                            for _, listing in _site_calls(fn, names)}
    return side(discover) & side(diagnose)


# ---------------------------------------------------------------------------
# Exemptions, each with its reason and the check that its reason still holds
# ---------------------------------------------------------------------------

def _shell_unbuilt(app: str) -> bool:
    """Whether the app is still a first shell. Its site module says it is
    not built, and its listing does nothing but refuse, whatever it is
    given."""
    path = REPO / "apps" / app / ("%s_site.py" % app)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {t.id for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)}
    (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "collect_documents"]
    body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return ("NOT_MAPPED" in names and len(body) == 1 and isinstance(body[0], ast.Raise)
            and "NotBuilt" in ast.unparse(body[0]))


def _is_a_number(node, tree) -> bool:
    """A whole number written out, or a module name set once to one."""
    if isinstance(node, ast.Constant):
        return type(node.value) is int and node.value > 0
    if isinstance(node, ast.Name):
        values = [n.value for n in tree.body if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name) and t.id == node.id]
        return len(values) == 1 and _is_a_number(values[0], tree)
    return False


def _diagnose_caps(app: str, listing: str, cap: str):
    """A check that the app's Diagnose still reads its listing with a set
    number of the newest pages, `cap` written as a whole number, so it
    looks rather than walks."""
    def holds():
        (entry,) = [p for p in ENTRIES if p.parent.name == app]
        tree = ast.parse(entry.read_text(encoding="utf-8"))
        functions, names = _functions(tree), _site_names(tree)
        reached = _reach(functions, "cmd_diagnose") - _reach(functions, "cmd_discover")
        calls = [c for n in reached for fn in functions[n]
                 for c, name in _site_calls(fn, names) if name == listing]
        return bool(calls) and all(any(k.arg == cap and _is_a_number(k.value, tree)
                                       for k in c.keywords) for c in calls)
    return holds


SHELL = ("a first shell another session is changing on this release. Its listing "
         "raises NotBuilt whatever it is given, so the report says the same either way. "
         "Hand it the settings when it is built.")
# The run's walk goes back from the newest page, and its date only ends the
# walk sooner. These Diagnoses read a set number of the newest pages on
# purpose, so they read the pages the run reads first, as many as their cap
# holds, and with a recent date that can be more than the run reads, never
# other pages. Venmo's Discover sets its floor in two steps, so handing it
# would take a helper both share.
LOOK = ("its Diagnose reads a set number of the newest pages on purpose, and the run's "
        "date only ends the walk sooner, so it reads the pages the run reads first, as "
        "many as its cap holds, and no other")
EXEMPT = {
    ("cibc", "collect_documents", "keep"): (SHELL, lambda: _shell_unbuilt("cibc")),
    ("cibc", "collect_documents", "config"): (SHELL, lambda: _shell_unbuilt("cibc")),
    ("mbna", "collect_documents", "keep"): (SHELL, lambda: _shell_unbuilt("mbna")),
    ("mbna", "collect_documents", "config"): (SHELL, lambda: _shell_unbuilt("mbna")),
    ("scalable", "collect_documents", "keep"): (SHELL, lambda: _shell_unbuilt("scalable")),
    ("scalable", "collect_documents", "config"): (SHELL, lambda: _shell_unbuilt("scalable")),
    ("venmo", "collect_download_docs", "floor"): (
        LOOK, _diagnose_caps("venmo", "collect_download_docs", "limit")),
    ("apple", "walk_purchases", "limit_date"): (
        LOOK, _diagnose_caps("apple", "walk_purchases", "max_batches")),
    ("uber", "walk_rides", "limit_date"): (LOOK, _diagnose_caps("uber", "walk_rides", "max_pages")),
    ("uber", "walk_eats", "limit_date"): (LOOK, _diagnose_caps("uber", "walk_eats", "max_pages")),
}

# The apps whose Diagnose was found leaving settings out, every one named,
# so a census that compared fewer is not mistaken for one that passed.
NAMED = {"netbenefits", "invest529", "amazonvisa", "dkb", "direkt1822", "renaultbank",
         "affirm", "fairfaxwater", "consorsbank", "fidelity", "sparkassepc", "ing",
         "redcard", "irs", "venmo", "apple", "uber", "cibc", "mbna", "scalable"}
# The apps whose report lists through a function its run reaches only
# inside the site module, read by the setting that function takes.
NAMED_TAKEN = {"ibkr", "vanguard"}
# Apps whose Discover hands the listing something that is no setting, a list
# it fills or a trace, which the census reads and lets through.
NOT_SETTINGS = {"amfam": "collect_download_docs", "golden1": "collect_download_docs",
                "statefarm": "collect_download_docs", "robinhood": "scroll_full_page"}


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_diagnose_lists_with_the_settings_its_discover_uses(entry):
    app = entry.parent.name
    left = ["%s(%s=) at line %d" % (listing, name, d)
            for listing, name, d in all_gaps_of(entry) if (app, listing, name) not in EXEMPT]
    assert not left, (
        "%s's Diagnose lists without settings its Discover lists with, so a support report "
        "can show nothing wrong where a run fails. Pass them as Discover writes them: %s"
        % (app, ", ".join(left)))


def test_the_census_compares_every_app_it_names():
    compared = {p.parent.name: gaps_of(p)[1] for p in ENTRIES}
    taken = {p.parent.name for p in ENTRIES
             if taken_in(p.read_text(encoding="utf-8"), p)[0]}
    assert len(ENTRIES) > 80
    missing = sorted(a for a in NAMED if not compared.get(a))
    assert not missing, ("compared nothing in", missing)
    # NetBenefits lists on two ways of Discover, one plan and several.
    assert compared["netbenefits"] >= 2
    missing = sorted(a for a in NAMED_TAKEN if a not in taken)
    assert not missing, ("read no setting a listing takes in", missing)


@pytest.mark.parametrize("app", sorted(NOT_SETTINGS))
def test_the_census_reads_what_is_no_setting_and_lets_it_through(app):
    (entry,) = [p for p in ENTRIES if p.parent.name == app]
    assert NOT_SETTINGS[app] in shared_listings(entry), "the census never compared it"
    assert gaps_of(entry)[0] == []


@pytest.mark.parametrize("key", sorted(EXEMPT), ids=lambda k: "%s-%s-%s" % k)
def test_an_exemption_holds_only_while_its_reason_does(key):
    app, listing, name = key
    reason, holds = EXEMPT[key]
    (entry,) = [p for p in ENTRIES if p.parent.name == app]
    assert any(g[:2] == (listing, name) for g in all_gaps_of(entry)), (
        "%s's Diagnose now passes %s to %s. Take it off the exemptions." % (app, name, listing))
    assert holds(), "%s's exemption no longer holds: %s" % (app, reason)


# ---------------------------------------------------------------------------
# What each Diagnose hands its listing when it runs
# ---------------------------------------------------------------------------

def checks_of(entry: Path):
    """Each setting to see handed when the app's Diagnose runs, by (listing,
    name), with each expression the run's value is made by and the function
    its locals are read in, None for the way every app writes it."""
    source, app = entry.read_text(encoding="utf-8"), entry.parent.name
    out = {}
    for _, _, listing, name, _, rexpr, _, rfn in wanted_in(source, entry)[0]:
        if (app, listing, name) not in EXEMPT:
            out.setdefault((listing, name), []).append((rexpr, rfn))
    for _, _, listing, name, _ in taken_in(source, entry)[0]:
        if (app, listing, name) not in EXEMPT and TAKEN[name] and (listing, name) not in out:
            out[(listing, name)] = [(ast.parse(TAKEN[name], mode="eval").body, None)]
    return out


COMPARED = [p for p in ENTRIES if gaps_of(p)[1] or taken_in(p.read_text(encoding="utf-8"), p)[0]]

# The command line, the start date in the config and the kinds it keeps.
SCOPES = {
    "unscoped": ([], None, None),
    "one year": (["--year", "2021"], None, None),
    "start date in the config": ([], "2019-06-01", None),
    "one kind kept": ([], None, ["Statement"]),
}


def _load(entry: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(entry.parent))
    try:
        return importlib.import_module(entry.stem)
    finally:
        sys.path.pop(0)


class _EmptyLocator:
    def count(self):
        return 0

    def nth(self, _i):
        return self

    @property
    def first(self):
        return self


class _EmptyPage:
    """A page that holds nothing, and nothing on it can be pressed."""
    url = "about:blank"

    def title(self):
        return ""

    def locator(self, *_a, **_k):
        return _EmptyLocator()

    get_by_role = locator

    def screenshot(self, *_a, **_k):
        return b""

    def evaluate(self, *_a, **_k):
        return None

    def wait_for_timeout(self, *_a, **_k):
        return None

    def is_closed(self):
        return False

    def on(self, *_a, **_k):
        return None

    remove_listener = on


def _empty_answer(name: str):
    if name.startswith(("goto_", "open_", "ensure_")):
        return True
    if name.startswith(("collect_", "find_", "shown_", "row_", "list_")):
        return []
    if "survey" in name:
        return {}
    return None


def _discover_value(expr, fn, mod, app):
    """What Discover's own expression for a setting makes of this app's
    config and command line."""
    if fn is not None:
        expr = _resolved(expr, fn)
    assert expr is not None, "Discover's setting is set more than once, so it is not read here"
    code = compile(ast.fix_missing_locations(ast.Expression(body=expr)), "<discover>", "eval")
    env = dict(vars(mod))
    env.setdefault("scope", run_scope)
    return eval(code, env, {"self": app})


def _same(handed, expected) -> bool:
    if callable(handed) or callable(expected):
        return (callable(handed) and callable(expected)
                and all(bool(handed(str(y))) == bool(expected(str(y)))
                        for y in range(1995, 2036)))
    return handed == expected


@pytest.mark.parametrize("scope_name", sorted(SCOPES))
@pytest.mark.parametrize("entry", COMPARED, ids=lambda p: p.parent.name)
def test_diagnose_hands_its_listing_what_discover_would(entry, scope_name, tmp_path,
                                                       monkeypatch, capsys):
    app_name = entry.parent.name
    checks = checks_of(entry)
    if not checks:
        pytest.skip("every setting this app's Diagnose leaves out is exempt")
    functions = _functions(ast.parse(entry.read_text(encoding="utf-8")))
    flags, start, kinds = SCOPES[scope_name]
    mod = _load(entry)
    site = mod.site
    example = entry.parent / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.pop("default_start_date", None)
    if start:
        config["default_start_date"] = start
    if kinds:
        config["document_types"] = kinds
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api

    def no_browser(*_a, **_k):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))
    page = _EmptyPage()
    apps = []

    def the_page(self, *_a, **_k):
        apps.append(self)
        return page
    monkeypatch.setattr(mod.App, "page", the_page)

    listings = {listing for listing, _ in checks}
    handed = {name: [] for name in listings}
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    names = _site_names(tree)
    called = {listing for name in _reach(functions, "cmd_diagnose") for fn in functions[name]
              for _, listing in _site_calls(fn, names)}

    def stand_in(name, real):
        def answer(*args, **kwargs):
            if name in listings:
                handed[name].append(inspect.signature(real).bind(*args, **kwargs).arguments)
                return []
            if name == "address_signed_out":
                return False
            if name == "is_safe_url":
                return True
            return _empty_answer(name)
        return answer

    for name in called | {"is_safe_url", "address_signed_out"}:
        real = getattr(site, name, None)
        if callable(real) and not isinstance(real, type):
            monkeypatch.setattr(site, name, stand_in(name, real))
    try:
        mod.main(["--config", str(cfg), "--diagnose"] + flags)
    except SystemExit as ended:
        assert ended.code in (0, None), capsys.readouterr().out[-1500:]
    said = capsys.readouterr().out
    assert apps, "Diagnose never asked for the page"
    app = apps[0]
    for (listing, name), ways in sorted(checks.items(), key=lambda kv: kv[0]):
        assert handed[listing], ("Diagnose never listed through %s" % listing, said[-1500:])
        for rexpr, rfn in ways:
            expected = _discover_value(rexpr, rfn, mod, app)
            for arguments in handed[listing]:
                assert name in arguments, (
                    "%s's Diagnose handed %s no %s" % (app_name, listing, name))
                assert _same(arguments[name], expected), (app_name, listing, name, scope_name)


# ---------------------------------------------------------------------------
# The census's own check, against the shapes it is there to catch and the
# shapes it lets through
# ---------------------------------------------------------------------------

RUN = '''
import x_site as site
from paperpull_core import scope

class App:
    def cmd_discover(self):
        page = self.page()
        keep = scope.period_filter(self.args, self.config)
        rows = site.collect_documents(page, keep=keep, config=self.config)
        trace = []
        more = site.collect_download_docs(page, trace=trace, rounds=6)
        notices = site.notice_rows(page, notices=self._reads_notices())
        floor, limit = self._floor(), 4
        old = site.walk(page, limit_date=floor)
        return rows

    def _reads_notices(self):
        return "Other Document" in (self.config.get("document_types") or [])

    def _floor(self):
        return self.args.start_date or ""

    def cmd_diagnose(self):
        page = self.page()
%s
'''


def _gaps(diagnose_body: str, site_source: str = None, run: str = RUN):
    body = "\n".join("        " + line for line in diagnose_body.strip().splitlines())
    return [g[:2] for g in gaps_in(run % body, site_source=site_source)[0]]


@pytest.mark.parametrize("body, missing", [
    ("docs = site.collect_documents(page)", {("collect_documents", "keep"),
                                             ("collect_documents", "config")}),
    ("docs = site.collect_documents(page, config=self.config)", {("collect_documents", "keep")}),
    ("docs = site.collect_documents(page, keep=scope.period_filter(self.args, self.config),"
     " config=None)", {("collect_documents", "config")}),
    ("docs = site.collect_documents(page, keep=None, config={})",
     {("collect_documents", "keep"), ("collect_documents", "config")}),
    ("docs = site.collect_documents(page, keep=lambda y: True, config=self.config)",
     {("collect_documents", "keep")}),
    # A keep built from anything but the run's own command line and config.
    ("docs = site.collect_documents(page, keep=scope.period_filter(argparse.Namespace(),"
     " self.config), config=self.config)", {("collect_documents", "keep")}),
    ("docs = site.collect_documents(page, keep=scope.period_filter(self.args, None),"
     " config=self.config)", {("collect_documents", "keep")}),
    ("docs = site.collect_documents(page, keep=scope.period_filter(self.args, {}),"
     " config=self.config)", {("collect_documents", "keep")}),
    ("docs = site.collect_documents(page, keep=scope.period_filter(self.args, self.config),"
     " config=dict(self.config, document_types=None))", {("collect_documents", "config")}),
    ("rows = site.notice_rows(page)", {("notice_rows", "notices")}),
    ("rows = site.notice_rows(page, notices=True)", {("notice_rows", "notices")}),
    ("rows = site.walk(page, max_pages=2)", {("walk", "limit_date")}),
    ("docs = []", set()),
])
def test_the_census_finds_a_setting_left_out(body, missing):
    assert set(_gaps(body)) == missing, body


def test_the_census_reads_a_listing_a_helper_makes():
    """A Diagnose that lists through a helper only it calls is read there."""
    src = RUN % "        return self._diagnose_list(page)" + '''
    def _diagnose_list(self, page):
        return site.collect_documents(page, config=self.config)
'''
    assert [g[:2] for g in gaps_in(src)[0]] == [("collect_documents", "keep")]


def test_the_census_reads_a_setting_a_discover_helper_sets():
    """Discover's setting in a local of a helper it reaches, as NetBenefits
    lists each of several plans."""
    src = '''
import x_site as site

class App:
    def cmd_discover(self):
        return self._each_plan(self.page())

    def _each_plan(self, page):
        keep = scope.period_filter(self.args, self.config)
        return site.collect_documents(page, keep=keep)

    def cmd_diagnose(self):
        return site.collect_documents(self.page())
'''
    assert [g[:2] for g in gaps_in(src)[0]] == [("collect_documents", "keep")]


def test_a_helper_both_sides_share_is_one_call():
    src = '''
import x_site as site

class App:
    def cmd_discover(self):
        return self._list(self.page())

    def _list(self, page):
        return site.collect_documents(page, config=self.config)

    def cmd_diagnose(self):
        return self._list(self.page())
'''
    assert gaps_in(src) == ([], 0)


def test_the_census_reads_another_name_for_the_site_module():
    src = (RUN % "        docs = portal.collect_documents(page)").replace(
        "import x_site as site", "import x_site as portal").replace("site.", "portal.")
    assert {g[:2] for g in gaps_in(src)[0]} >= {("collect_documents", "keep"),
                                                ("collect_documents", "config")}


def test_the_census_reads_a_function_imported_by_name():
    src = '''
from x_site import collect_documents as listed

class App:
    def cmd_discover(self):
        return listed(self.page(), config=self.config)

    def cmd_diagnose(self):
        return listed(self.page())
'''
    assert [g[:2] for g in gaps_in(src)[0]] == [("collect_documents", "config")]


def test_the_census_reads_settings_spread_into_the_call():
    src = '''
import x_site as site

class App:
    def cmd_discover(self):
        opts = {"config": self.config}
        return site.collect_documents(self.page(), **opts)

    def cmd_diagnose(self):
%s
'''
    left = lambda body: [g[:2] for g in gaps_in(src % ("        " + body))[0]]  # noqa: E731
    assert left("return site.collect_documents(self.page(), **{})") == [
        ("collect_documents", SPREAD)]
    assert left("return site.collect_documents(self.page())") == [("collect_documents", SPREAD)]
    assert left('return site.collect_documents(self.page(), **{"config": self.config})') == []


def test_the_census_reads_a_setting_handed_in_its_place():
    """A setting Discover hands by its place is wanted by its name too, and
    Diagnose may hand it either way."""
    site_source = "def collect_documents(page, keep=None, config=None):\n    return []\n"
    src = RUN.replace("site.collect_documents(page, keep=keep, config=self.config)",
                      "site.collect_documents(page, keep, self.config)")
    left = lambda body: {g[:2] for g in gaps_in(src % ("        " + body),  # noqa: E731
                                                site_source=site_source)[0]
                         if g[0] == "collect_documents"}
    assert left("docs = site.collect_documents(page)") == {
        ("collect_documents", "keep"), ("collect_documents", "config")}
    assert left("docs = site.collect_documents(page, None, self.config)") == {
        ("collect_documents", "keep")}
    assert left("docs = site.collect_documents(page, scope.period_filter(self.args, "
                "self.config), config=self.config)") == set()


def test_the_page_is_not_a_setting():
    """The page reaches the browser through the config, and is still where a
    listing reads rather than what it is asked for."""
    src = '''
import x_site as site

class App:
    def page(self):
        return connect(self.config["cdp_url"])

    def cmd_discover(self):
        page = self.page()
        site.collect_download_docs(page)

    def cmd_diagnose(self):
        site.collect_download_docs(None)
'''
    assert gaps_in(src) == ([], 0)


def test_what_the_script_keeps_on_itself_is_not_followed():
    """A list a listing fills is kept on the app, as a floor read from the
    config can be, and neither marks every value kept there a setting."""
    src = '''
import x_site as site

class App:
    def cmd_discover(self):
        self.floor = self.config.get("default_start_date")
        self._discovery_facts = {}
        site.collect_download_docs(self.page(), self._discovery_facts, trace=self._trace)

    def cmd_diagnose(self):
        site.collect_download_docs(self.page())
'''
    assert gaps_in(src) == ([], 0)


TAKES = '''
def collect_months(page, keep=None, why=None):
    return []

def walk(page, limit_date="", max_pages=None):
    return []

def survey(page, *, config=None):
    return {}
'''


@pytest.mark.parametrize("body, missing", [
    ("site.collect_months(page)", {("collect_months", "keep")}),
    ("site.collect_months(page, keep=None)", {("collect_months", "keep")}),
    ("site.collect_months(page, keep=scope.period_filter(self.args, None))",
     {("collect_months", "keep")}),
    ("site.collect_months(page, scope.period_filter(self.args, self.config))", set()),
    ("site.collect_months(page, keep=scope.period_filter(self.args, self.config), why=[])", set()),
    ("site.walk(page, max_pages=2)", {("walk", "limit_date")}),
    ("site.walk(page, limit_date=self._floor(), max_pages=2)", set()),
    ("site.survey(page)", {("survey", "config")}),
    ("site.survey(page, config=self.config)", set()),
])
def test_the_census_reads_a_setting_a_listing_takes(body, missing):
    """A report that lists through a function its run never calls itself is
    read by the settings that function takes, as Interactive Brokers' and
    Vanguard's are."""
    src = '''
import x_site as site
from paperpull_core import scope

class App:
    def cmd_discover(self):
        return site.collect_documents(self.page(), keep=scope.period_filter(self.args, self.config))

    def _floor(self):
        return self.args.start_date or ""

    def cmd_diagnose(self):
        page = self.page()
        %s
''' % body
    assert {g[:2] for g in taken_gaps_in(src, site_source=TAKES)} == missing, body


def test_a_cap_is_a_whole_number():
    tree = ast.parse("DIAGNOSE_PAGES = 3\nNONE = None\nTWICE = 2\nTWICE = 4\n")
    number = lambda src: _is_a_number(ast.parse(src, mode="eval").body, tree)  # noqa: E731
    assert number("2") and number("DIAGNOSE_PAGES")
    assert not number("None") and not number("NONE") and not number("missing")
    assert not number("0") and not number("TWICE") and not number("self.cap")


def test_a_place_in_a_walk_is_not_a_setting():
    """A year or a page a loop walks over is a place in the run's walk, and
    a Diagnose that looks at one place is not leaving a setting out."""
    src = '''
import x_site as site

class App:
    def cmd_discover(self):
        page = self.page()
        for year in self.args.years:
            site.goto_orders(page, year)

    def cmd_diagnose(self):
        site.goto_orders(self.page())
'''
    assert gaps_in(src) == ([], 0)


@pytest.mark.parametrize("body", [
    "docs = site.collect_documents(page, keep=scope.period_filter(self.args, self.config),"
    " config=self.config)",
    "keep = scope.period_filter(self.args, self.config)\n"
    "docs = site.collect_documents(page, keep=keep, config=self.config)",
    "cfg = self.config\n"
    "docs = site.collect_documents(page, keep=scope.period_filter(self.args, cfg), config=cfg)",
    "docs = site.collect_documents(page, keep=scope.period_filter(self.args, self.config),"
    " config=self.config, navigate=False)",
    # A trace, a constant and a list it fills are no settings, so none is compared.
    "docs = site.collect_download_docs(page)",
    "rows = site.notice_rows(page, notices=self._reads_notices())",
    "rows = site.walk(page, limit_date=self._floor(), max_pages=2)",
])
def test_the_census_lets_through_what_a_run_lists_with(body):
    assert _gaps(body) == [], body
