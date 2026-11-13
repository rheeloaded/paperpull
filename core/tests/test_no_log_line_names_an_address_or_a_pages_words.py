"""No log line names a page's address or says what a page or an answer said.

Every app logs at INFO to a file in its output folder and to the console,
which the panel shows, and a tester copies either into a public issue as
easily as a Diagnose file. Discover Bank logged the address its tab was on,
its documents address, a statement's whole PDF address with the account's
id in it, an error's own text, and up to 300 characters of what Discover
answered for a PDF it refused. A Playwright error names the address it was
at and can quote the page, so an error's text is the page's too. The census
of what Diagnose prints (test_what_diagnose_prints_keeps_no_word_off_the_list)
reads every log line in the code Diagnose runs, and leaves out on purpose
the site module's own lines, since that module serves every command. So
nothing read the lines a Run All writes, and the same lines were in most
apps.

So every log call in every app's site module and entry module
(*_site.py, *_docs.py and *_receipts.py) is read here with ast. A call
fails when one of its values, outside a call that names it safely, is

    an address   an attribute or a name that says url or href (page.url,
                 r.url, href, doc.href), or a key url, href, link or
                 location, or a name made from one of those in the same
                 function, as `started_at = page.url` makes started_at
    an error     the name an enclosing `except ... as e` bound, or a name
                 made from it, in any form, str(e) and e.args among them
    an answer    what a page or an answer gave, a call of text, inner_text,
                 text_content, inner_html, content, body, json,
                 input_value, get_attribute or evaluate, a key text, body,
                 message, error, html, detail or msg, or a name made from one
    a traceback  log.exception, or exc_info, which writes the error's text

The safe ways are urls.where_it_leads for a place, its scheme and host,
failure.error_kind for an error, its kind as a word, the words module's
shape, shape_label, shape_url and shape_tree for anything a page wrote,
redact, and type, len, int, float and bool. A status key is a number the
app's own page script or Playwright puts there, so it is read as one.

What this cannot see is a value handed in from somewhere else, a title or
an account name a caller passed as a parameter. A name is followed only
inside one function, and only through calls that give back what they were
handed (str, join, split and the like). So a name such as title, label or
account is not caught here, and those were looked at by hand in the apps
this census fixed.

When this was written the rule found 581 lines in 166 files. Discover
Bank's and the four apps a review named, Chase, Ally, Robinhood and
Discover's card app, were fixed with it (86 lines), along with the lines
there that named a title, an account or a control's label. The rest, 495
lines in 160 files, are LEFT, each file with how many it holds, so a new
line in any file fails here, and a file that holds fewer than LEFT says
must have its number lowered, which keeps the list from going stale.
Nothing here is a real value.
"""
import ast
import functools
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# What a logging call is, the method and the object it is called on.
LOGS = frozenset({"info", "warning", "warn", "error", "exception", "critical", "debug",
                  "log"})
LOGGER = re.compile(r"(^|\.)(_?log|logger|LOG|logging|_?LOGGER)$")

# Calls that say a value safely, or say only its size or its type.
SAFE = frozenset({"where_it_leads", "error_kind", "_error_kind", "redact", "shape",
                  "shape_label", "shape_url", "shape_name", "shape_tree", "shape_query",
                  "safe_query", "type", "len", "int", "float", "bool", "isinstance"})

# An address, by a name or an attribute that says so, or by a key.
ADDRESS_NAME = re.compile(r"url|href", re.I)
ADDRESS_KEYS = frozenset({"url", "href", "link", "location"})

# What a page or an answer gave.
ANSWER_CALLS = frozenset({"text", "inner_text", "text_content", "inner_html", "content",
                          "body", "json", "all_text_contents", "all_inner_texts",
                          "input_value", "get_attribute", "evaluate", "evaluate_handle"})
ANSWER_KEYS = frozenset({"text", "body", "message", "error", "html", "detail",
                         "errorMessage", "msg"})
# A number the app's own page script or Playwright puts in an answer.
NUMBER_KEYS = frozenset({"status"})

# Calls whose answer is still what they were handed, so a name made with
# one carries what it was made from.
PASSING = frozenset({"str", "repr", "format", "join", "urljoin", "join_url", "urlsplit",
                     "urlparse", "unquote", "quote", "strip", "lstrip", "rstrip", "lower",
                     "upper", "split", "rsplit", "splitlines", "partition", "rpartition",
                     "replace", "encode", "decode", "removeprefix", "removesuffix",
                     "casefold", "title", "capitalize"})

NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def is_log_call(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOGS and bool(LOGGER.search(ast.unparse(node.func.value))))


def called(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _key(node):
    """The constant key of a subscript or of a .get call, or None."""
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value
    if isinstance(node, ast.Call) and called(node) == "get" and node.args \
            and isinstance(node.func, ast.Attribute) and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    return None


def raw(expr, made: dict, errors, following: bool = False) -> list:
    """(kind, source) for every part of expr that says an address, an error
    or an answer, never looking inside a call that says it safely. With
    following, a call is looked into only when it gives back what it was
    handed (PASSING), which is how a name is followed."""
    out = []
    todo = [expr]
    while todo:
        n = todo.pop()
        key = _key(n)
        if key in NUMBER_KEYS:
            continue
        if key in ANSWER_KEYS:
            out.append(("answer", ast.unparse(n)))
            continue
        if key in ADDRESS_KEYS:
            out.append(("address", ast.unparse(n)))
            continue
        if isinstance(n, ast.Call):
            name = called(n)
            if name in SAFE:
                continue
            if isinstance(n.func, ast.Attribute) and name in ANSWER_CALLS:
                out.append(("answer", ast.unparse(n)))
                continue
            if following and name not in PASSING:
                continue
            if isinstance(n.func, ast.Attribute):
                todo.append(n.func.value)
            todo.extend(n.args)
            todo.extend(k.value for k in n.keywords)
            continue
        if isinstance(n, ast.Attribute):
            if n.attr in ("__name__", "__class__", "__qualname__"):
                continue
            if ADDRESS_NAME.search(n.attr):
                out.append(("address", ast.unparse(n)))
                continue
            todo.append(n.value)
            continue
        if isinstance(n, ast.Name):
            if n.id in errors:
                out.append(("error", n.id))
            elif ADDRESS_NAME.search(n.id):
                out.append(("address", n.id))
            elif n.id in made:
                out.append((made[n.id], n.id))
            continue
        if isinstance(n, NESTED):
            continue
        todo.extend(ast.iter_child_nodes(n))
    return out


def own_nodes(fn):
    """Every node of a function's own body, and none of a function or class
    defined in it."""
    todo = list(fn.body)
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, NESTED):
            todo.extend(ast.iter_child_nodes(node))


def errors_around(fn) -> dict:
    """{id of each log call: the names the except clauses around it bound}."""
    out = {}

    def walk(node, names):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, NESTED):
                continue
            if isinstance(child, ast.ExceptHandler) and child.name:
                walk(child, names | {child.name})
                continue
            if is_log_call(child):
                out[id(child)] = names
            walk(child, names)

    walk(fn, frozenset())
    return out


def made_from(nodes) -> dict:
    """{name: kind} for each name a function makes, by a plain assignment,
    from an address, an error or an answer. `nodes` is the function's own."""
    errors = {n.name for n in nodes if isinstance(n, ast.ExceptHandler) and n.name}
    assigns = [n for n in nodes if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name)]
    made = {}
    # Again, so a name made from a name made later in the text is caught.
    for _ in range(4):
        for node in assigns:
            parts = raw(node.value, made, errors, following=True)
            if parts:
                made.setdefault(node.targets[0].id, parts[0][0])
    return made


def lines_of(source: str) -> list:
    """(line, [(kind, source)]) for every log call in source that says an
    address, an error, an answer or a traceback."""
    tree = ast.parse(source)
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodes = list(own_nodes(fn))
        calls = [n for n in nodes if is_log_call(n)]
        if not calls:
            continue
        around, made = errors_around(fn), made_from(nodes)
        for node in calls:
            args = list(node.args)
            if args and isinstance(args[0], ast.Constant):
                args = args[1:]
            parts = []
            for arg in args:
                parts += raw(arg, made, around.get(id(node), frozenset()))
            if node.func.attr == "exception" or any(
                    k.arg == "exc_info" and not (isinstance(k.value, ast.Constant)
                                                 and not k.value.value)
                    for k in node.keywords):
                parts.append(("traceback", "log." + node.func.attr))
            if parts:
                found.append((node.lineno, sorted(set(parts))))
    return sorted(found)


def app_modules():
    out = []
    for app in sorted((REPO / "apps").iterdir()):
        if not app.is_dir():
            continue
        for pattern in ("*_site.py", "*_docs.py", "*_receipts.py"):
            out += sorted(app.glob(pattern))
    return out


MODULES = app_modules()


def name_of(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


@functools.lru_cache(maxsize=None)
def found_in(name: str) -> list:
    """lines_of an app's module, read once for every test that asks."""
    return lines_of((REPO / name).read_text(encoding="utf-8"))


# The files fixed with this census, which hold no such line now.
FIXED = ("apps/discoverbank/discoverbank_site.py", "apps/discoverbank/discoverbank_docs.py",
         "apps/chase/chase_site.py", "apps/ally/ally_site.py",
         "apps/robinhood/robinhood_site.py", "apps/discovercard/discovercard_site.py")

# Every other file that held such lines when this census was written, with
# how many, measured on 2026-11-12 from main at b7b4bbab. Of the 495 lines,
# 354 say an error's own text, 95 are log.exception or exc_info, 54 name an
# address and 20 say an answer, and a line can say more than one. They are
# left only because fixing all of them at once was more than one change
# should carry, never because they are safe. Each waits for its own fix,
# which lowers its number here or takes it out. A file holding more than
# its number fails, so no new line joins them, and one holding fewer fails
# until its number is lowered.
LEFT = {
    "apps/aafmaa/aafmaa_docs.py": 1,
    "apps/aafmaa/aafmaa_site.py": 12,
    "apps/adp/adp_docs.py": 1,
    "apps/adp/adp_site.py": 6,
    "apps/affirm/affirm_docs.py": 1,
    "apps/affirm/affirm_site.py": 2,
    "apps/ally/ally_docs.py": 4,
    "apps/alpaca/alpaca_site.py": 4,
    "apps/amazon/amazon_receipts.py": 6,
    "apps/amazon/amazon_site.py": 2,
    "apps/amex/amex_docs.py": 1,
    "apps/amex/amex_site.py": 5,
    "apps/amexbanking/amexbanking_docs.py": 1,
    "apps/amexbanking/amexbanking_site.py": 1,
    "apps/amfam/amfam_docs.py": 1,
    "apps/amfam/amfam_site.py": 3,
    "apps/anthem/anthem_docs.py": 3,
    "apps/anthem/anthem_site.py": 10,
    "apps/apple/apple_receipts.py": 4,
    "apps/applecard/applecard_docs.py": 1,
    "apps/applecard/applecard_site.py": 3,
    "apps/att/att_docs.py": 2,
    "apps/att/att_site.py": 18,
    "apps/bestbuy/bestbuy_receipts.py": 7,
    "apps/bestbuy/bestbuy_site.py": 4,
    "apps/bilt/bilt_site.py": 2,
    "apps/bofa/bofa_docs.py": 1,
    "apps/capitalone/capitalone_docs.py": 1,
    "apps/capitalone/capitalone_site.py": 7,
    "apps/cetera/cetera_docs.py": 1,
    "apps/cetera/cetera_site.py": 2,
    "apps/chase/chase_docs.py": 1,
    "apps/chasebusiness/chasebusiness_site.py": 3,
    "apps/cibc/cibc_docs.py": 1,
    "apps/cibc/cibc_site.py": 1,
    "apps/citi/citi_docs.py": 1,
    "apps/citi/citi_site.py": 1,
    "apps/coinbase/coinbase_docs.py": 2,
    "apps/coinbase/coinbase_site.py": 5,
    "apps/consorsbank/consorsbank_docs.py": 1,
    "apps/consorsbank/consorsbank_site.py": 1,
    "apps/costco/costco_receipts.py": 6,
    "apps/costco/costco_site.py": 8,
    "apps/discovercard/discovercard_docs.py": 1,
    "apps/dkb/dkb_docs.py": 3,
    "apps/dkb/dkb_site.py": 1,
    "apps/dominion/dominion_docs.py": 1,
    "apps/dominion/dominion_site.py": 5,
    "apps/ebay/ebay_receipts.py": 6,
    "apps/ebay/ebay_site.py": 3,
    "apps/etrade/etrade_docs.py": 1,
    "apps/etrade/etrade_site.py": 8,
    "apps/ezpassva/ezpassva_docs.py": 1,
    "apps/ezpassva/ezpassva_site.py": 3,
    "apps/fairfaxwater/fairfaxwater_docs.py": 1,
    "apps/fairfaxwater/fairfaxwater_site.py": 2,
    "apps/fedex/fedex_docs.py": 1,
    "apps/fedex/fedex_site.py": 2,
    "apps/fidelity/fidelity_docs.py": 1,
    "apps/fidelity/fidelity_site.py": 1,
    "apps/firsthorizon/firsthorizon_site.py": 3,
    "apps/gap/gap_receipts.py": 6,
    "apps/gap/gap_site.py": 2,
    "apps/github/github_receipts.py": 5,
    "apps/github/github_site.py": 3,
    "apps/golden1/golden1_docs.py": 2,
    "apps/golden1/golden1_site.py": 8,
    "apps/homedepot/homedepot_receipts.py": 6,
    "apps/homedepot/homedepot_site.py": 1,
    "apps/ibkr/ibkr_docs.py": 1,
    "apps/ibkr/ibkr_site.py": 7,
    "apps/ing/ing_docs.py": 3,
    "apps/invest529/invest529_docs.py": 1,
    "apps/invest529/invest529_site.py": 1,
    "apps/irs/irs_site.py": 3,
    "apps/kroger/kroger_receipts.py": 6,
    "apps/kroger/kroger_site.py": 3,
    "apps/lowes/lowes_receipts.py": 6,
    "apps/lowes/lowes_site.py": 2,
    "apps/mbna/mbna_docs.py": 1,
    "apps/mbna/mbna_site.py": 1,
    "apps/meijer/meijer_receipts.py": 6,
    "apps/meijer/meijer_site.py": 7,
    "apps/mtb/mtb_docs.py": 1,
    "apps/mtb/mtb_site.py": 5,
    "apps/myecp/myecp_docs.py": 1,
    "apps/myecp/myecp_site.py": 1,
    "apps/mypay/mypay_docs.py": 1,
    "apps/mypay/mypay_site.py": 3,
    "apps/navyfederal/navyfederal_docs.py": 1,
    "apps/navyfederal/navyfederal_site.py": 3,
    "apps/nelnet/nelnet_docs.py": 1,
    "apps/nelnet/nelnet_site.py": 3,
    "apps/netbenefits/netbenefits_docs.py": 2,
    "apps/netbenefits/netbenefits_site.py": 3,
    "apps/newrez/newrez_docs.py": 3,
    "apps/newrez/newrez_site.py": 7,
    "apps/nwnatural/nwnatural_docs.py": 1,
    "apps/nwnatural/nwnatural_site.py": 1,
    "apps/optum/optum_docs.py": 1,
    "apps/optum/optum_site.py": 1,
    "apps/paylocity/paylocity_docs.py": 1,
    "apps/paylocity/paylocity_site.py": 2,
    "apps/paypal/paypal_docs.py": 5,
    "apps/paypal/paypal_site.py": 4,
    "apps/pge/pge_docs.py": 1,
    "apps/pge/pge_site.py": 6,
    "apps/portlandgeneral/portlandgeneral_docs.py": 1,
    "apps/portlandgeneral/portlandgeneral_site.py": 3,
    "apps/redcard/redcard_docs.py": 1,
    "apps/redcard/redcard_site.py": 4,
    "apps/robinhood/robinhood_docs.py": 9,
    "apps/sba/sba_docs.py": 1,
    "apps/sba/sba_site.py": 1,
    "apps/scalable/scalable_docs.py": 1,
    "apps/scalable/scalable_site.py": 1,
    "apps/schwab/schwab_docs.py": 1,
    "apps/schwab/schwab_site.py": 7,
    "apps/sdge/sdge_docs.py": 1,
    "apps/sdge/sdge_site.py": 3,
    "apps/shelbycounty/shelbycounty_docs.py": 1,
    "apps/shelbycounty/shelbycounty_site.py": 2,
    "apps/simmons/simmons_site.py": 2,
    "apps/smud/smud_docs.py": 1,
    "apps/smud/smud_site.py": 3,
    "apps/spectrum/spectrum_site.py": 3,
    "apps/statefarm/statefarm_docs.py": 1,
    "apps/statefarm/statefarm_site.py": 11,
    "apps/stripe/stripe_docs.py": 1,
    "apps/stripe/stripe_site.py": 2,
    "apps/target/target_receipts.py": 12,
    "apps/target/target_site.py": 2,
    "apps/tmobile/tmobile_docs.py": 1,
    "apps/tmobile/tmobile_site.py": 2,
    "apps/treasurydirect/treasurydirect_site.py": 3,
    "apps/tsp/tsp_docs.py": 1,
    "apps/tsp/tsp_site.py": 1,
    "apps/tualatin/tualatin_docs.py": 1,
    "apps/tualatin/tualatin_site.py": 4,
    "apps/uber/uber_receipts.py": 2,
    "apps/ukg/ukg_docs.py": 1,
    "apps/ups/ups_docs.py": 1,
    "apps/ups/ups_site.py": 1,
    "apps/usaa/usaa_docs.py": 1,
    "apps/usaa/usaa_site.py": 5,
    "apps/usbank/usbank_docs.py": 1,
    "apps/usbank/usbank_site.py": 23,
    "apps/vanguard/vanguard_docs.py": 1,
    "apps/vanguard/vanguard_site.py": 6,
    "apps/venmo/venmo_site.py": 3,
    "apps/verizon/verizon_docs.py": 1,
    "apps/verizon/verizon_site.py": 4,
    "apps/verizonmobile/verizonmobile_docs.py": 1,
    "apps/verizonmobile/verizonmobile_site.py": 3,
    "apps/walmart/walmart_receipts.py": 7,
    "apps/wealthfront/wealthfront_docs.py": 7,
    "apps/wealthfront/wealthfront_site.py": 4,
    "apps/wellsfargo/wellsfargo_docs.py": 1,
    "apps/ziply/ziply_docs.py": 1,
    "apps/ziply/ziply_site.py": 2,
}


# -- the rule itself ------------------------------------------------------------------

CAUGHT = [
    ('log.info("at %s", page.url)', "address"),
    ('log.info(f"at {page.url}")', "address"),
    ('log.info("asked %s", r.url)', "address"),
    ('log.info("asked %s", url)', "address"),
    ('log.info("asked %s", doc.href)', "address"),
    ('log.info("asked %s", item.get("href"))', "address"),
    ('here = page.url\nlog.info("from %s", here)', "address"),
    ('full = join_url(BASE, href)\nlog.info("from %s", full)', "address"),
    ('host = urlparse(url).hostname\nlog.info("host %s", host)', "address"),
    ('try:\n    go()\nexcept Exception as e:\n    log.info("failed: %s", e)', "error"),
    ('try:\n    go()\nexcept Exception as e:\n    log.info("failed: %s", str(e).splitlines()[0][:70])',
     "error"),
    ('try:\n    go()\nexcept Exception as e:\n    log.info("failed: %s", e.args)', "error"),
    ('try:\n    go()\nexcept Exception as e:\n    err = e\n    log.info("failed: %s", err)',
     "error"),
    ('log.info("said %s", page.inner_text("main"))', "answer"),
    ('words = page.locator("h1").text_content()\nlog.info("said %s", words)', "answer"),
    ('got = page.evaluate(JS)\nlog.info("said %s", got)', "answer"),
    ('log.error("answered %s", result.get("text"))', "answer"),
    ('log.error("answered %s", result["body"])', "answer"),
    ('err = result.get("message") or "none"\nlog.error("answered %s", err[:300])', "answer"),
    ('log.exception("failed on %s", key)', "traceback"),
    ('log.warning("failed", exc_info=True)', "traceback"),
    ('logger.info("at %s", page.url)', "address"),
    ('self.log.info("at %s", page.url)', "address"),
    ('logging.info("at %s", page.url)', "address"),
]

PASSED = [
    'log.info("at %s", where_it_leads(page.url))',
    'log.info("at %s", shape_url(page.url, words))',
    'try:\n    go()\nexcept Exception as e:\n    log.info("failed (%s)", error_kind(e))',
    'try:\n    go()\nexcept Exception as e:\n    log.info("failed (%s)", type(e).__name__)',
    'try:\n    go()\nexcept Exception as e:\n    log.info("failed (%s)", failure.error_kind(e))',
    'rows = page.evaluate(JS)\nlog.info("%d rows", len(rows))',
    'got = page.evaluate(JS, url)\nlog.info("answered %s", got.get("status"))',
    'log.info("named %s", shape_label(page.inner_text("h1")))',
    'log.info("%d accounts on the menu", count)',
    'log.info("statement %d refused", i + 1)',
    'log.warning("failed", exc_info=False)',
    'resp = page.request.get(href)\nlog.info("answered HTTP %s", resp.status)',
    'print("at", page.url)',
]


def _in_a_function(snippet: str) -> str:
    return "def f(page, r, url, doc, item, link, result, key, words, count, i, href):\n" + \
        "\n".join("    " + line for line in snippet.splitlines())


@pytest.mark.parametrize("snippet,kind", CAUGHT, ids=[c[0][:60] for c in CAUGHT])
def test_the_rule_catches(snippet, kind):
    found = lines_of(_in_a_function(snippet))
    assert found and kind in {k for _, parts in found for k, _ in parts}, found


@pytest.mark.parametrize("snippet", PASSED, ids=[p[:60] for p in PASSED])
def test_the_rule_passes(snippet):
    assert lines_of(_in_a_function(snippet)) == []


def test_the_census_reads_every_app():
    names = {p.parent.name for p in MODULES}
    apps = {d.name for d in (REPO / "apps").iterdir() if d.is_dir() and any(
        d.glob(pattern) for pattern in ("*_site.py", "*_docs.py", "*_receipts.py"))}
    assert names == apps and len(apps) > 80
    assert all(name in {name_of(p) for p in MODULES} for name in FIXED)


# -- every app ------------------------------------------------------------------------

def _said(path, found) -> str:
    return "\n".join("  %s:%d %s" % (name_of(path), line, ", ".join(
        "%s %s" % (kind, src) for kind, src in parts)) for line, parts in found)


@pytest.mark.parametrize("path", MODULES, ids=name_of)
def test_no_new_log_line_names_an_address_or_a_pages_words(path):
    found = found_in(name_of(path))
    allowed = LEFT.get(name_of(path), 0)
    assert len(found) <= allowed, (
        "%d log line(s) here name an address or say what a page or an error said, where "
        "%d may until this file is fixed. Say a place with urls.where_it_leads, an error "
        "with failure.error_kind, and a page's words with words.shape_label.\n%s"
        % (len(found), allowed, _said(path, found)))


@pytest.mark.parametrize("name", sorted(LEFT), ids=str)
def test_no_file_is_left_more_lines_than_it_holds(name):
    path = REPO / name
    assert path.exists(), "%s is gone, so take it out of LEFT" % name
    found = found_in(name)
    assert len(found) == LEFT[name], (
        "%s holds %d such line(s) and LEFT says %d, so lower its number in LEFT, or take "
        "it out when it holds none" % (name, len(found), LEFT[name]))


def test_no_fixed_file_is_left():
    assert not set(FIXED) & set(LEFT)
