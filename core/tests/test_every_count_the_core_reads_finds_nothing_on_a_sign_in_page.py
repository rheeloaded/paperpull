"""Every reader whose work the core reads finds nothing on a sign-in page.

A Diagnose whose app's own checks said it was signed out, or met a security
check, and that read nothing, ends as a report that read nothing, and the
panel tells the person to sign in (paperpull_core.words). A count of what
was read, or a list of the documents recognized, says the report read
something whatever a check said, so it is a report saved. That holds only
for what a reader of the provider's own list read. A loose scrape of every
row or link on the page counts a sign-in page's own lists of links, so a
report made signed out would say it was saved. T-Mobile's Diagnose counted
such a scrape as "collected", and on a sign-in page with a list of help
links its report was called saved.

So every reader whose count an app's Diagnose writes under a key of
COUNT_KEYS, or whose documents it lists under a key of LIST_KEYS, is run
here, the app's own function, against three made-up pages. A sign-in page
with lists of links, a security check, and a sign-in page that also lists
dated notices with View and Download controls. Each must find nothing, or
refuse with one of the errors a reader refuses with, which Diagnose writes
as an error and no count. A refusal's documents, where it carries some,
are what it found. A reader that fails any other way fails here, since
then nothing is proven.

Each reader runs as its Diagnose calls it. Every argument the call hands it
beside the page is given here, a constant as written, the run's config as
the app's config.example.json, the run's keep as scope.period_filter makes
it for a run with no period of its own, which keeps everything, and an
argument of the Diagnose's own walk as GIVEN names it. A reader handed
anything else is named with what it reads, and not run.

A refusal proves only what it says. About half of the readers refuse
before reading these pages at all, because the address is not their
provider's, because the address they go to never answers here, every
request being refused, because a request from a made-up page fails, or
because a made-up page has no origin of its own, so a script reading its
cookies is refused.
For those this shows that nothing is counted where the reader cannot reach
its list, not what it would count on a sign-in page at its own address.
Each of them today is asked only once its app found the documents page, or
reads its provider's own answers rather than the page.

On the dated page alone two kinds are named. Eight apps whose "collected"
the core read before it read anything else, whose Diagnose-only or
fallback scrape counts a dated row with a View, Open or PDF control. And
four whose run's reader counts such notices, which their Diagnose asks
only once goto_documents found the documents page, which each refuses on a
page its sign-in check calls signed out. Each named one must still count
there, so the name comes off when it stops.

The pages are shown to be ones a loose scrape counts rows on, so a scrape
put where the core reads fails here. Nothing leaves the browser, every
request is refused, and every value is invented.
"""
import argparse
import ast
import copy
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core import scope  # noqa: E402
from paperpull_core.words import COUNT_KEYS, LIST_KEYS  # noqa: E402

import test_every_diagnose_counts_under_a_key_the_core_reads as census  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")

REPO = census.REPO

NAV = """<header><nav><ul>
  <li><a href="/personal">Personal</a></li><li><a href="/business">Business</a></li>
  <li><a href="/help">Help and support</a></li><li><a href="/locations">Find a branch</a></li>
</ul></nav></header>"""
FORM = """<h1>Sign in to your account</h1>
<form><label>Username <input name="u"></label>
<label>Password <input type="password" name="p"></label>
<button type="submit">Sign in</button></form>
<ul class="help"><li><a href="/forgot">Forgot username or password?</a></li>
<li><a href="/enroll">Enroll in online banking</a></li></ul>"""
FOOT = """<footer><ul><li><a href="/privacy">Privacy</a></li><li><a href="/terms">Terms of use</a></li>
<li><a href="/security">Security center</a></li><li>Copyright 2031 Example Bank</li></ul></footer>"""
NOTICES = """<section class="notices"><h2>Notices</h2><ul>
<li>March 4, 2031 Changes to your account agreement <a href="/notice-1.pdf">View PDF</a></li>
<li>01/15/2031 Updated schedule of fees <a href="/fees.pdf" download>Download statement of fees</a></li>
</ul><table><tbody>
<tr><td>Feb 2, 2031</td><td>Privacy notice</td><td><a href="/privacy-2031">View</a></td></tr>
<tr><td>12/09/2030</td><td>Holiday hours</td><td><button type="button">Open</button></td></tr>
</tbody></table></section>"""
PAGE = "<!doctype html><html><head><title>%s</title></head><body>%s</body></html>"

SIGN_IN = PAGE % ("Sign in", NAV + "<main>" + FORM + "</main>" + FOOT)
CHECK = PAGE % ("Verify it's you", """<h1>We need to confirm it's you</h1>
<p>Choose how to get a code.</p>
<ul><li><a href="#text">Text me at the number ending 99</a></li><li><a href="#call">Call me</a></li>
<li><a href="#email">Email me</a></li></ul>
<p><a href="/help">Need help?</a></p>""")
DATED = PAGE % ("Sign in", NAV + "<main>" + FORM + NOTICES + "</main>" + FOOT)

PAGES = {"sign-in page": SIGN_IN, "security check": CHECK, "sign-in page with dated notices": DATED}

# What a reader raises when the page is not its list, which Diagnose writes
# as an error and no count.
REFUSALS = frozenset({"SessionExpired", "ListStopped", "NotBuilt", "RuntimeError",
                      "Error", "TimeoutError"})

# The readers the core reads the work of that are handed something this
# cannot make, with what each reads and what was measured. They are not run.
MORE_THAN_THE_PAGE = {
    ("schwab", "documents_total"):
        "the documents API, asked for the accounts site.list_accounts read from Schwab's "
        "answer first. On each of these pages list_accounts raises Playwright's Error (it "
        "cannot make the API's address), so the Diagnose writes no count. list_documents "
        "alone, given a made-up account, stops on a key the real list carries (KeyError "
        "'charitable')",
}

# How the arguments a Diagnose hands its reader beside the page are given
# here, by the expression the Diagnose writes, so each reader runs as its
# Diagnose calls it.
STAND_INS = {
    "self.config": "the app's own config.example.json, what an install starts with, over its "
                   "SPEC.config_defaults, as load_config fills them",
    "scope.period_filter(self.args, self.config)":
        "the real scope.period_filter of a run with no period of its own and that config, "
        "None, keep all, since keep only narrows what is listed",
    "self._reads_notices()": "True, the reader's own default, which opens the notices list too",
    "self._only_accounts()": "the last fours the config's only_accounts names, none in the "
                             "template, so every account, as an install starts (Wells Fargo, #221)",
}

# Arguments a Diagnose hands one reader that are of its own walk, by name,
# each with what it is given here. A thing the reader fills starts empty.
GIVEN = {
    ("ibkr", "documents_total"): {"why": []},
    ("newrez", "documents_recognized"): {"walk": {}},
    # The label of the card the walk is on, read off the page before the
    # list. A sign-in page shows none, and the label only names the rows.
    ("amex", "collected"): {"account": ""},
}

_KNOWN = ("a scrape of every row holding a date and a View, Open or PDF control, read as "
          "collected before this change")
_GATED = ("its run's reader counts dated notices, and its Diagnose asks it only once "
          "goto_documents found the documents page, which it refuses where its sign-in check "
          "calls the page signed out")
DATED_NAMED = {
    ("ally", "collected"): _KNOWN, ("chase", "collected"): _KNOWN,
    ("discoverbank", "collected"): _KNOWN, ("discovercard", "collected"): _KNOWN,
    ("dominion", "collected"): _KNOWN, ("robinhood", "collected"): _KNOWN,
    ("verizon", "collected"): _KNOWN, ("wealthfront", "collected"): _KNOWN,
    ("sba", "documents_recognized"): _GATED, ("smud", "documents_recognized"): _GATED,
    ("wellsfargo", "documents_recognized"): _GATED, ("newrez", "documents_recognized"): _GATED,
}

# Loose scrapes whose count the core reads past, which these pages must
# catch. T-Mobile's was read as collected.
SCRAPES = (("adp", "collect_documents"), ("treasurydirect", "collect_documents"),
           ("tmobile", "collect_documents"))


def _source(value):
    """The expression a count or a list is made from, through len(), a
    comprehension and a slice."""
    if isinstance(value, ast.IfExp):
        value = value.body
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "len":
        value = value.args[0] if value.args else None
    elif isinstance(value, ast.ListComp):
        value = value.generators[0].iter
    else:
        return None
    if isinstance(value, ast.Subscript):
        value = value.value
    return value


def _site_call(node):
    if isinstance(node, ast.IfExp):
        node = node.body
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "site"):
        return node
    return None


def _made_by(func, source):
    """The site call a counted or listed value came from, or None. A name is
    the one the function last set from a site call."""
    if source is None:
        return None
    if not isinstance(source, ast.Name):
        return _site_call(source)
    made = None
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and _site_call(node.value) is not None
                and any(isinstance(t, ast.Name) and t.id == source.id for t in node.targets)):
            if made is None or node.lineno > made.lineno:
                made = node
    return _site_call(made.value) if made is not None else None


def reads_in(path: Path):
    """(app, key, call) for each count or list the core reads in a Diagnose
    finding, call None where it was not made by a site call."""
    out = []
    for func, _name, writes, _reads in census._findings(path):
        for key, value in writes:
            if key in COUNT_KEYS and census._is_count(value) and not isinstance(value, ast.Constant):
                out.append((path.parent.name, key, _made_by(func, _source(value))))
            elif key in LIST_KEYS and isinstance(value, ast.ListComp):
                out.append((path.parent.name, key, _made_by(func, _source(value))))
    return out


READS = [r for path in census.ENTRIES for r in reads_in(path)]


def _arguments(app, key, call):
    """How each argument the call hands its reader beside the page is given
    here, by name, as ("constant", value), ("stand-in", expression) or
    ("given", value), or None when the call hands it something this cannot
    give. A positional argument past the page is given only by GIVEN, in
    the order GIVEN names them, and every argument the call passes is given,
    none left out. GIVEN gives only what the Diagnose passes as a bare name
    of its own, never what it writes as a constant or an expression the
    stand-ins make, so it cannot run a reader narrower than its Diagnose."""
    if call is None or not call.args:
        return None
    given = GIVEN.get((app, key), {})
    names = list(given)
    extra = call.args[1:]
    if len(extra) > len(names) or not all(isinstance(a, ast.Name) for a in extra):
        return None
    spec = {names[i]: ("given", given[names[i]]) for i in range(len(extra))}
    for kw in call.keywords:
        text = ast.unparse(kw.value)
        if not kw.arg or kw.arg in spec:
            return None
        if kw.arg in given:
            if not isinstance(kw.value, ast.Name):
                return None
            spec[kw.arg] = ("given", given[kw.arg])
        elif isinstance(kw.value, ast.Constant):
            spec[kw.arg] = ("constant", kw.value.value)
        elif text in STAND_INS:
            spec[kw.arg] = ("stand-in", text)
        else:
            return None
    return spec


def _config_of(app: str) -> dict:
    """The app's config.example.json over its SPEC.config_defaults, the way
    load_config fills what a config file leaves out. load_config itself is
    not called, since it sets the core's storage for the whole process."""
    example = json.loads((REPO / "apps" / app / "config.example.json").read_text(encoding="utf-8"))
    for name in [m for m in list(sys.modules) if m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        defaults = dict(importlib.import_module("storage").SPEC.config_defaults)
    finally:
        sys.path.pop(0)
    return {**copy.deepcopy(defaults), **example}


def _stand_in(text: str, app: str):
    config = _config_of(app)
    if text == "self.config":
        return config
    if text == "scope.period_filter(self.args, self.config)":
        return scope.period_filter(argparse.Namespace(), config)
    if text == "self._reads_notices()":
        return True
    if text == "self._only_accounts()":
        return list(config.get("only_accounts") or [])
    raise KeyError(text)


def resolve(app: str, spec: dict) -> dict:
    """The arguments themselves, made fresh for each page, since a reader
    may fill what it is handed."""
    out = {}
    for name, (how, value) in spec.items():
        if how == "stand-in":
            out[name] = _stand_in(value, app)
        else:
            out[name] = copy.deepcopy(value)
    return out


RUN = sorted({(app, key): (app, key, call.func.attr, _arguments(app, key, call))
              for app, key, call in READS
              if (app, key) not in MORE_THAN_THE_PAGE
              and _arguments(app, key, call) is not None}.values(),
             key=lambda r: (r[0], r[1]))


def site_of(app: str):
    for name in [m for m in list(sys.modules) if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        return importlib.import_module("%s_site" % app)
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


def _found(fn, browser, html, kws=()):
    """What fn finds on a page of its own showing html, 0 for a refusal, and
    the error's name for anything else. A page of its own, since a reader
    that goes to an address of its own leaves its page in no state for the
    next."""
    pg = browser.new_page()
    try:
        pg.route("**/*", lambda route: route.abort())
        # Waits a twentieth of the reader's own, since a made-up page that
        # never changes shows nothing more for waiting. Several readers wait
        # out their own list for a minute.
        real = pg.wait_for_timeout
        pg.wait_for_timeout = lambda ms: real(max(1, int(ms) // 20))
        pg.set_default_timeout(3000)
        pg.set_content(html)
        try:
            got = fn(pg, **dict(kws))
        except Exception as e:
            if type(e).__name__ not in REFUSALS:
                return "raised %s" % type(e).__name__
            # Three apps write what a stopped list carries into the list
            # the core reads.
            return len(getattr(e, "docs", None) or [])
        return 0 if got is None else len(got)
    finally:
        pg.close()


def test_the_census_runs_the_readers():
    assert len(READS) >= 70, "the census found what the core reads"
    assert len(RUN) >= 65, "the census runs most of them"


def test_every_reader_is_run_or_named():
    run = {(app, key) for app, key, _n, _k in RUN}
    unread = sorted("%s %s" % (app, key) for app, key, _c in READS
                    if (app, key) not in run and (app, key) not in MORE_THAN_THE_PAGE)
    assert not unread, ("these are read by the core from a reader this cannot run, so say "
                        "what each reads in MORE_THAN_THE_PAGE: %s" % ", ".join(unread))
    reads = {(app, key) for app, key, _c in READS}
    for named in (MORE_THAN_THE_PAGE, GIVEN, DATED_NAMED):
        assert set(named) <= reads, set(named) - reads


def test_every_argument_given_is_one_the_call_passes():
    """GIVEN names arguments a call passes, never the whole call, so none of
    what a Diagnose hands its reader is left out here, as IBKR's keep was
    when its why was given for the whole call."""
    calls = {(app, key): call for app, key, call in READS}
    for (app, key), given in GIVEN.items():
        call = calls[(app, key)]
        passed = len(call.args) - 1 + len(call.keywords)
        spec = _arguments(app, key, call)
        assert spec is not None and len(spec) == passed, (app, key, ast.unparse(call), spec)
        assert set(given) <= set(spec), (app, key, set(given) - set(spec))
    for app, key, _name, spec in RUN:
        call = calls[(app, key)]
        assert len(spec) == len(call.args) - 1 + len(call.keywords), (app, key, ast.unparse(call))


def test_a_positional_argument_given_is_the_readers_own_parameter():
    """A positional argument past the page takes GIVEN's name in order, so
    the name must be the reader's own parameter in that place, or the value
    would land on another parameter and the one the Diagnose passes would
    keep its default."""
    calls = {(app, key): call for app, key, call in READS}
    checked = 0
    for app, key, name, spec in RUN:
        extra = calls[(app, key)].args[1:]
        if not extra:
            continue
        params = list(inspect.signature(getattr(site_of(app), name)).parameters)[1:1 + len(extra)]
        assert params == list(GIVEN[(app, key)])[:len(extra)], (app, key, params)
        checked += 1
    assert checked >= 1, "Newrez's walk is passed by position"


def test_given_names_only_what_a_diagnose_passes_as_a_name(monkeypatch):
    monkeypatch.setitem(GIVEN, ("nothing", "collected"), {"limit": 5})
    assert _arguments("nothing", "collected", _call("site.f(page, limit=2)")) is None
    monkeypatch.setitem(GIVEN, ("nothing", "collected"), {"keep": None})
    assert _arguments("nothing", "collected", _call(
        "site.f(page, keep=scope.period_filter(self.args, self.config))")) is None
    monkeypatch.setitem(GIVEN, ("nothing", "collected"), {"walk": {}})
    assert _arguments("nothing", "collected", _call("site.f(page, {})")) is None


def test_the_config_holds_the_apps_own_defaults():
    """What load_config fills from SPEC.config_defaults is in the config
    here, under what the example file sets."""
    for app, _key, _name, spec in RUN:
        if ("stand-in", "self.config") not in spec.values():
            continue
        config = _config_of(app)
        sys.path.insert(0, str(REPO / "apps" / app))
        try:
            sys.modules.pop("storage", None)
            defaults = importlib.import_module("storage").SPEC.config_defaults
        finally:
            sys.path.pop(0)
        assert set(defaults) <= set(config), (app, set(defaults) - set(config))


def test_every_stand_in_is_made_for_every_app_that_needs_it():
    """Each app's config.example.json reads, and a run with no period of its
    own keeps everything, so keep is never narrower here than a run's."""
    for app, _key, _name, spec in RUN:
        for how, value in spec.values():
            if how == "stand-in":
                made = _stand_in(value, app)
                if value.startswith("scope.period_filter"):
                    assert made is None, (app, "the example config sets a period")


def _call(src):
    return ast.parse(src).body[0].value


@pytest.mark.parametrize("src, wanted", [
    ("site.f(page)", {}),
    ("site.f(page, limit=2)", {"limit": ("constant", 2)}),
    ("site.f(page, keep=scope.period_filter(self.args, self.config), config=self.config)",
     {"keep": ("stand-in", "scope.period_filter(self.args, self.config)"),
      "config": ("stand-in", "self.config")}),
])
def test_the_arguments_a_call_passes_are_each_given(src, wanted):
    assert _arguments("nothing", "collected", _call(src)) == wanted


@pytest.mark.parametrize("src", [
    "site.f(page, keep=keep)",
    "site.f(page, accounts)",
    "site.f(page, config=self.other)",
    "site.f(page, **extra)",
    "site.f()",
])
def test_an_argument_this_cannot_give_leaves_the_reader_unrun(src):
    assert _arguments("nothing", "collected", _call(src)) is None


def test_a_given_argument_joins_the_others_and_drops_none(monkeypatch):
    monkeypatch.setitem(GIVEN, ("nothing", "collected"), {"why": []})
    spec = _arguments("nothing", "collected",
                      _call("site.f(page, keep=scope.period_filter(self.args, self.config), why=why)"))
    assert spec == {"keep": ("stand-in", "scope.period_filter(self.args, self.config)"),
                    "why": ("given", [])}
    spec = _arguments("nothing", "collected", _call("site.f(page, walk)"))
    assert spec == {"why": ("given", [])}, "a positional argument takes GIVEN's names in order"


def test_what_a_reader_is_handed_is_made_fresh_for_each_page():
    spec = {"why": ("given", []), "limit": ("constant", 2)}
    first, second = resolve("ibkr", spec), resolve("ibkr", spec)
    first["why"].append("filled by a reader")
    assert second["why"] == [] and spec["why"] == ("given", [])


@pytest.mark.parametrize("app, key, name, spec", RUN, ids=["%s-%s" % (a, k) for a, k, _n, _w in RUN])
def test_a_reader_the_core_reads_finds_nothing_on_a_sign_in_page(browser, app, key, name, spec):
    fn = getattr(site_of(app), name)
    found = {where: _found(fn, browser, html, resolve(app, spec)) for where, html in PAGES.items()}
    dated = found.pop("sign-in page with dated notices")
    assert not any(found.values()), (
        "%s's Diagnose writes what site.%s read under %s, which the core reads as something "
        "read, and it found %s on a made-up page. A report made signed out would say it was "
        "saved. Count a loose scrape under rows_collected." % (app, name, key, found))
    if (app, key) in DATED_NAMED:
        assert isinstance(dated, int) and dated > 0, (
            "%s %s no longer counts the dated notices, so take it off DATED_NAMED (%s)"
            % (app, key, dated))
    else:
        assert not dated, ("%s's site.%s, read under %s, found %s on a sign-in page with dated "
                           "notices" % (app, name, key, dated))


@pytest.mark.parametrize("app, name", SCRAPES, ids=[a for a, _n in SCRAPES])
def test_the_pages_are_ones_a_loose_scrape_counts_rows_on(browser, app, name):
    fn = getattr(site_of(app), name)
    for where, html in PAGES.items():
        assert _found(fn, browser, html) > 0, (app, where)


def test_a_reader_that_fails_another_way_is_not_taken_for_a_refusal(browser):
    def broken(_page):
        raise AttributeError("a reader with a mistake in it")
    assert _found(broken, browser, SIGN_IN) == "raised AttributeError"


def test_a_refusal_that_carries_documents_found_them(browser):
    class ListStopped(Exception):
        def __init__(self, docs):
            super().__init__("the list stopped")
            self.docs = docs

    def stopped(_page):
        raise ListStopped(["a sign-in page's link", "another"])
    assert _found(stopped, browser, SIGN_IN) == 2
