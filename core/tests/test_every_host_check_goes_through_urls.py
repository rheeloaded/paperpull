"""Every check of a host by its ending, and every link resolved against a
page, goes through paperpull_core.urls.

Python and a browser read some addresses differently. urlsplit ends a host
at a slash, a browser also at a backslash, so
`https://evil.example\\.chase.com/x` has the Python host
`evil.example\\.chase.com`, which ends in `.chase.com`, and the browser host
evil.example. And urljoin reads `///evil.example/x` or `/\\evil.example/x`
on a Chase page as a path on Chase, where a browser goes to evil.example.

The shared guard refuses a host that is not a plain name and a backslash
before the query (urls.host_of, urls.host_matches), and urls.join gives
nothing for a link a browser could resolve elsewhere. Nine functions in six
apps had written `host.endswith("." + domain)` of their own, Apple Card's
beside a fetch, and none of them refused it. Two apps checked urljoin's
answer and then pressed the link itself, American Family and
TreasuryDirect. So both live in one place, and the census here finds a new
copy written the way those were. It cannot see every way a host could be
compared, a regular expression or a host passed between functions, which
is why the guards themselves refuse the shapes.
"""
import ast
import importlib
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from paperpull_core.urls import host_matches  # noqa: E402

THE_ONE = Path("core") / "paperpull_core" / "urls.py"
SCANNED = ("apps", "core", "gui", "server", "tools")
NOT_SOURCE = {"tests", "node_modules", "build", "dist", "__pycache__", "site-packages"}

# The last label of a domain's ending, as opposed to a file's (".pdf.delivering").
DOMAIN_ENDS = {"com", "net", "org", "gov", "mil", "edu", "io", "us", "co", "me", "uk",
               "de", "ca", "app", "dev", "bank", "info", "biz", "markets", "finance"}


def _source_files(root: Path):
    for top in SCANNED:
        for here, dirs, files in os.walk(root / top):
            # Pruned by name before descending, so a worktree's linked
            # environments (.venv junctions) are never walked into.
            dirs[:] = [d for d in dirs if d not in NOT_SOURCE and not d.startswith(".")]
            for name in files:
                if not name.endswith(".py") or name.startswith("test_") or name == "conftest.py":
                    continue
                yield Path(here) / name


def _reads_a_host(fn) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr in ("hostname", "netloc")
               for n in ast.walk(fn))


def _by_label(arg) -> bool:
    """A suffix written to match by label, "." + x or f".{x}"."""
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        left = arg.left
        return isinstance(left, ast.Constant) and isinstance(left.value, str) \
            and left.value.startswith(".")
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
        return (isinstance(first, ast.Constant) and isinstance(first.value, str)
                and first.value.startswith(".")
                and any(isinstance(v, ast.FormattedValue) for v in arg.values))
    return False


def _domain_ending(arg) -> bool:
    """A written ending that is a domain's, such as ".id.me"."""
    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
        return False
    labels = arg.value.lower().split(".")
    return arg.value.startswith(".") and len(labels) >= 3 and labels[-1] in DOMAIN_ENDS


def _plain_words(arg) -> bool:
    """A constant that cannot be a host's ending, such as " Report", or a
    file's, such as ".pdf". A host's ending has two labels or more."""
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
        and (not arg.value.startswith(".") or arg.value.count(".") == 1)


def own_host_checks(source: str):
    """(line, text) of each ending check that compares a host by itself.

    Three shapes. An ending built to match by label anywhere, `"." + domain`
    or f".{domain}", since nothing but a host is matched that way. A written
    domain ending anywhere, such as ".anthem.com". And any ending checked
    inside a function that reads a parsed address's host, unless what it
    checks for is plain words."""
    tree = ast.parse(source)
    lines = source.splitlines()
    found = set()
    scopes = [tree] + [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
    for scope in scopes:
        host_here = scope is not tree and _reads_a_host(scope)
        for call in ast.walk(scope):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "endswith" and call.args):
                continue
            arg = call.args[0]
            args = list(arg.elts) if isinstance(arg, (ast.Tuple, ast.List)) else [arg]
            if any(_by_label(a) or _domain_ending(a) for a in args) or (
                    host_here and not all(_plain_words(a) for a in args)):
                found.add((call.lineno, lines[call.lineno - 1].strip()))
    return sorted(found)


def own_link_joins(source: str):
    """(line, text) of each urljoin taken or called, by any name."""
    tree = ast.parse(source)
    lines = source.splitlines()
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and any(a.name == "urljoin" for a in n.names):
            found.add(n.lineno)
        elif isinstance(n, ast.Attribute) and n.attr == "urljoin":
            found.add(n.lineno)
        elif isinstance(n, ast.Name) and n.id == "urljoin":
            found.add(n.lineno)
    return [(line, lines[line - 1].strip()) for line in sorted(found)]


def _census(ask, word):
    offenders = []
    for path in _source_files(REPO):
        rel = path.relative_to(REPO)
        if rel == THE_ONE:
            continue
        source = path.read_text(encoding="utf-8")
        if word not in source:
            continue
        for line, text in ask(source):
            offenders.append("%s:%d %s" % (rel.as_posix(), line, text))
    return offenders


def test_no_app_compares_a_host_by_its_ending_on_its_own():
    offenders = _census(own_host_checks, "endswith")
    assert not offenders, (
        "Compare a host with paperpull_core.urls.host_matches(host_of(url), ...), "
        "which refuses a host that is not a plain name:\n  " + "\n  ".join(offenders))


def test_no_app_resolves_a_link_with_urljoin():
    offenders = _census(own_link_joins, "urljoin")
    assert not offenders, (
        "Resolve a link with paperpull_core.urls.join, which gives nothing for "
        "one a browser could resolve to another host:\n  " + "\n  ".join(offenders))


# -- the census sees the shapes it is for --------------------------------------

def test_the_census_sees_every_shape_the_nine_copies_had():
    seen = own_host_checks('''
from urllib.parse import urlsplit, urlparse

def one(url):
    host = (urlsplit(url).hostname or "").lower()
    return host == "anthem.com" or host.endswith(".anthem.com")

def two(url, hosts):
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)

def three(h, domains):
    return any(h == d or h.endswith("." + d) for d in domains)

def four(host, d):
    return host.endswith(f".{d}")

def five(url, suffix):
    return urlparse(url).netloc.endswith(suffix)

def six(url):
    return urlsplit(url).hostname.endswith((".apple.com", ".icloud.com"))

def seven(url):
    h = _host(url)
    return h.endswith(".id.me") or h.endswith([".login.gov"])
''')
    assert [line for line, _ in seen] == [6, 10, 13, 16, 19, 22, 26]


def test_the_census_leaves_alone_what_is_not_a_host():
    assert own_host_checks('''
from urllib.parse import urlsplit
from paperpull_core.urls import host_matches, host_of

def on_host(url, hosts):
    return host_matches(host_of(url), hosts)

def is_pdf(name):
    return name.lower().endswith(".pdf") or name.endswith((".zip", ".xlsx"))

def staged(name):
    return name.endswith(".pdf.delivering") or name.endswith(".tar.gz")

def summary(url, text):
    host = urlsplit(url).hostname
    return host and text.endswith(" Report")

def ends_in_pdf(url):
    parts = urlsplit(url)
    return parts.hostname and parts.path.lower().endswith(".pdf")
''') == []


def test_the_census_sees_urljoin_by_any_name():
    seen = own_link_joins('''
from urllib.parse import urljoin
from urllib.parse import urlsplit, urljoin as uj
import urllib.parse
from paperpull_core.urls import join as join_url

def a(page, href):
    return urljoin(page.url, href)

def b(page, href):
    return urllib.parse.urljoin(page.url, href)

def c(page, href):
    return join_url(page.url, href)
''')
    assert [line for line, _ in seen] == [2, 3, 8, 11]


# -- and the nine, asked what each was asked -----------------------------------

def _site(app):
    for name in [m for m in sys.modules if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        return importlib.import_module("%s_site" % app)
    finally:
        sys.path.pop(0)


class _Page:
    def __init__(self, url):
        self.url = url


def _domains(site, attr):
    value = getattr(site, attr) if attr.isupper() or attr.startswith("_") else attr
    return [value] if isinstance(value, str) else sorted(value)


# (app, function, its domains as a constant's name or a domain, takes a page)
THE_NINE = [
    ("anthem", "is_anthem_owned", "anthem.com", False),
    ("applecard", "_on_sign_in_host", "SIGN_IN_HOSTS", False),
    ("applecard", "_is_apple_file_host", "apple.com", False),
    ("discoverbank", "looks_moved_to_capital_one", "MOVED_HOSTS", True),
    ("discovercard", "looks_moved_to_capital_one", "MOVED_HOSTS", True),
    ("golden1", "_on_vendor_host", "VENDOR_HOSTS", False),
    ("golden1", "on_bank_host", "BANK_DOMAIN", False),
    ("irs", "on_identity_host", "IDENTITY_HOSTS", False),
]

# Each is evil.example to a browser, and once was the domain's to these.
BACKSLASHED = ["https://evil.example\\.%s/x", "https://evil.example\\@www.%s/x",
               "https://evil.example\\@%s/x"]


@pytest.mark.parametrize("app,fn,domains,takes_page", THE_NINE,
                         ids=["%s.%s" % (a, f) for a, f, _, _ in THE_NINE])
def test_each_host_check_refuses_a_backslashed_host(app, fn, domains, takes_page):
    site = _site(app)
    check = getattr(site, fn)
    ask = (lambda u: check(_Page(u))) if takes_page else check
    for d in _domains(site, domains):
        good = "https://www.%s/x" % d
        assert ask(good), "%s.%s refuses %s" % (app, fn, good)
        for shape in BACKSLASHED:
            bad = shape % d
            assert not ask(bad), "%s.%s accepts %s" % (app, fn, bad)


def test_golden1_never_names_a_backslashed_host_as_its_own():
    site = _site("golden1")
    for d in site._KNOWN_DOMAINS:
        assert site._where("https://www.%s/x" % d) in (d, "www." + d)
        for shape in BACKSLASHED:
            assert site._where(shape % d) == "nowhere", shape % d


def test_host_matches_is_what_the_census_points_to():
    assert host_matches("secure.chase.com", ["chase.com"])
    assert not host_matches("evil.example\\.chase.com", ["chase.com"])


# -- the two apps that pressed a link checked only by urljoin ------------------

LINKS_ELSEWHERE = ["/\\evil.example/billing", "///evil.example/billing",
                   "https:///evil.example/billing", "\\\\evil.example/billing"]


def test_american_family_refuses_a_link_a_browser_resolves_elsewhere():
    """The check before the Bill details press, as it asks it."""
    from urllib.parse import urljoin
    from paperpull_core.urls import join
    site = _site("amfam")
    assert "_address_allowed(join_url(" in Path(site.__file__).read_text(encoding="utf-8")
    assert site._address_allowed(join(site.BILLING_URL, "/billing"))
    for href in LINKS_ELSEWHERE:
        assert not site._address_allowed(join(site.BILLING_URL, href)), href
    # What urljoin made of the slashes, and the check took for American Family's.
    assert site._address_allowed(urljoin(site.BILLING_URL, "///evil.example/billing"))


def test_treasurydirect_refuses_a_link_a_browser_resolves_elsewhere():
    """The check before a press, as it asks it."""
    from paperpull_core.urls import join
    site = _site("treasurydirect")
    assert "is_signed_in_url(join_url(" in Path(site.__file__).read_text(encoding="utf-8")
    page = "https://www.treasurydirect.gov/RS/UN/Portfolio.do"
    for href in LINKS_ELSEWHERE:
        assert join(page, href) == "", href
        assert not site.is_signed_in_url(join(page, href)), href
