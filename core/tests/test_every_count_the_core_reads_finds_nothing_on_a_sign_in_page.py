"""Every count the core reads finds nothing on a sign-in page.

A Diagnose whose app's own checks said it was signed out, or met a security
check, and that counted nothing, ends as a report that read nothing, and the
panel tells the person to sign in (paperpull_core.words, COUNT_KEYS). A
count there says the report read rows whatever a check said, so it is a
report saved. That holds only for a count of what a reader of the
provider's own list read. A loose scrape of every row or link on the page
counts a sign-in page's own lists of links, so a report made signed out
would say it was saved. T-Mobile's Diagnose counted such a scrape as
"collected", and on a sign-in page with a list of help links its report was
called saved.

So every count an app's Diagnose writes under a key the core reads is run
here, the app's own function, against a made-up sign-in page and a made-up
security check, each with the lists of links such pages have. Each must
find nothing, or raise, which Diagnose writes as an error and no count. A
function that reads more than the page is named with what it reads. The
pages are shown to be ones a loose scrape counts rows on, ADP's,
TreasuryDirect's and T-Mobile's, so a scrape put under a key the core reads
fails here.

The functions are found as test_every_diagnose_counts_under_a_key_the_core_
reads.py finds the findings. A count is a len() of a call to the app's site
module, or of a name the same function last set from one. Nothing leaves the
browser, every request is refused, and every value is invented.
"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from paperpull_core.words import COUNT_KEYS  # noqa: E402

import test_every_diagnose_counts_under_a_key_the_core_reads as census  # noqa: E402

sync_api = pytest.importorskip("playwright.sync_api")

REPO = census.REPO

SIGN_IN = """<!doctype html><html><head><title>Sign in</title></head><body>
<header><nav><ul>
  <li><a href="/personal">Personal</a></li><li><a href="/business">Business</a></li>
  <li><a href="/help">Help and support</a></li><li><a href="/locations">Find a branch</a></li>
</ul></nav></header>
<main><h1>Sign in to your account</h1>
<form><label>Username <input name="u"></label>
<label>Password <input type="password" name="p"></label>
<button type="submit">Sign in</button></form>
<ul class="help"><li><a href="/forgot">Forgot username or password?</a></li>
<li><a href="/enroll">Enroll in online banking</a></li></ul></main>
<footer><ul><li><a href="/privacy">Privacy</a></li><li><a href="/terms">Terms of use</a></li>
<li><a href="/security">Security center</a></li><li>Copyright 2031 Example Bank</li></ul></footer>
</body></html>"""

CHECK = """<!doctype html><html><head><title>Verify it's you</title></head><body>
<h1>We need to confirm it's you</h1><p>Choose how to get a code.</p>
<ul><li><a href="#text">Text me at the number ending 99</a></li><li><a href="#call">Call me</a></li>
<li><a href="#email">Email me</a></li></ul>
<p><a href="/help">Need help?</a></p></body></html>"""

PAGES = {"sign-in page": SIGN_IN, "security check": CHECK}

# The counts the core reads that are made from more than the page, with
# what each reads. They are not run here.
MORE_THAN_THE_PAGE = {
    ("amex", "collected"): "the statements page's list for one card, which takes the card",
    ("fidelity", "collected"): "the Document Access Hub's own API, asked with the run's config",
    ("ibkr", "documents_total"): "the months the Date select offers under Monthly",
    ("ing", "collected"): "the Postbox's own list, asked with the run's config",
    ("schwab", "documents_total"): "the documents API, asked for each account",
    ("sparkassepc", "collected"): "the Postfach's own list, asked with the run's config",
}

# Loose scrapes, each the function an app's Diagnose counts under
# rows_collected or links_collected, which these pages must catch.
SCRAPES = (("adp", "collect_documents"), ("treasurydirect", "collect_documents"),
           ("tmobile", "collect_documents"))


def _len_of(value):
    if isinstance(value, ast.IfExp):
        value = value.body
    if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and value.func.id == "len" and value.args):
        return value.args[0]
    return None


def _made_by(func, counted):
    """The call a counted value came from, or None."""
    if isinstance(counted, ast.Call):
        return counted
    if not isinstance(counted, ast.Name):
        return None
    made = None
    for node in ast.walk(func):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and any(isinstance(t, ast.Name) and t.id == counted.id for t in node.targets)):
            if made is None or node.lineno > made.lineno:
                made = node.value
    return made


def counts_in(path: Path):
    """(app, key, call) for each count the core reads in a Diagnose finding."""
    out = []
    for func, _name, writes, _reads in census._findings(path):
        for key, value in writes:
            counted = _len_of(value) if key in COUNT_KEYS else None
            if counted is not None:
                out.append((path.parent.name, key, _made_by(func, counted)))
    return out


COUNTS = [c for path in census.ENTRIES for c in counts_in(path)]


def _site_call(call):
    """The name of site.<name>(page), the page alone, or None."""
    if (call is not None and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name) and call.func.value.id == "site"
            and len(call.args) == 1 and not call.keywords):
        return call.func.attr
    return None


RUN = sorted({(app, key, _site_call(call)) for app, key, call in COUNTS
              if _site_call(call) and (app, key) not in MORE_THAN_THE_PAGE})


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


def _found(fn, browser, html):
    """What fn counts on a page of its own showing html, since a reader that
    goes to an address of its own leaves its page in no state for the next."""
    pg = browser.new_page()
    try:
        pg.route("**/*", lambda route: route.abort())
        pg.set_content(html)
        try:
            return len(fn(pg))
        except Exception:
            # Diagnose writes what a reader raised as an error, and no count.
            return 0
    finally:
        pg.close()


def test_the_census_runs_the_counts():
    assert len(COUNTS) >= 50, "the census found the counts"
    assert len(RUN) >= 40, "the census runs most of them"


def test_every_count_is_run_or_named():
    unread = sorted("%s %s" % (app, key) for app, key, call in COUNTS
                    if not _site_call(call) and (app, key) not in MORE_THAN_THE_PAGE)
    assert not unread, ("these count under a key the core reads from more than the page, "
                        "so say what each reads in MORE_THAN_THE_PAGE: %s" % ", ".join(unread))
    named = {(app, key) for app, key, call in COUNTS if not _site_call(call)}
    assert set(MORE_THAN_THE_PAGE) <= named, set(MORE_THAN_THE_PAGE) - named


@pytest.mark.parametrize("app, key, name", RUN, ids=["%s-%s" % (a, k) for a, k, _n in RUN])
def test_a_count_the_core_reads_finds_nothing_on_a_sign_in_page(browser, app, key, name):
    fn = getattr(site_of(app), name)
    found = {where: _found(fn, browser, html) for where, html in PAGES.items()}
    assert not any(found.values()), (
        "%s's Diagnose counts site.%s under %s, which the core reads as rows read, and it "
        "found %s on a made-up page. A report made signed out would say it was saved. Count "
        "a loose scrape under rows_collected, and name the app in SCRAPE_ONLY."
        % (app, name, key, found))


@pytest.mark.parametrize("app, name", SCRAPES, ids=[a for a, _n in SCRAPES])
def test_the_pages_are_ones_a_loose_scrape_counts_rows_on(browser, app, name):
    fn = getattr(site_of(app), name)
    for where, html in PAGES.items():
        assert _found(fn, browser, html) > 0, (app, where)
