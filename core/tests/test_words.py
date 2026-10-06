"""The word list every file a tester may post is built from.

A word on the list leaves as the page wrote it. Any other word leaves as
its shape, every letter as a and every digit as 9. These are the rules that
make that true, tried with invented values made of letters and digits, the
kind redaction let through. Nothing here is a real value.
"""
import ast
import dataclasses
import json
import random
import re
import string
import sys
import types
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
REPO = CORE.parent
sys.path.insert(0, str(CORE))

from paperpull_core import words as W  # noqa: E402
from paperpull_core.redact import set_private_words  # noqa: E402

MERCHANT = "QZ4XKRWPT7MVN"        # thirteen letters and digits
LETTERS = "QZXKRWPTKMVNB"         # thirteen letters
SURNAME = "Zorvexquill"
STREET = "Quillfeather"


@pytest.fixture(autouse=True)
def _no_owner():
    set_private_words([])
    yield
    set_private_words([])


# -- one string ----------------------------------------------------------------

def test_a_word_on_the_list_stays_as_the_page_wrote_it():
    assert W.shape("Bill and Payment HISTORY") == "Bill and Payment HISTORY"
    assert W.shape("eStatements") == "eStatements"


def test_any_other_word_leaves_as_its_shape():
    assert W.shape("Statement for %s" % SURNAME) == "Statement for aaaaaaaaaaa"
    assert W.shape("0400 %s Lane" % STREET) == "9999 aaaaaaaaaaaa aaaa"
    assert W.shape(MERCHANT) == "aa9aaaaaa9aaa"
    assert W.shape(LETTERS) == "aaaaaaaaaaaaa"


def test_every_digit_is_a_9_whatever_it_sits_beside():
    assert W.shape("Checking ...0400") == "Checking ...9999"
    assert W.shape("March 2031") == "March 9999"
    assert W.shape("page2") == "page9"


def test_an_email_and_an_amount_are_written_as_words_of_ours():
    """Their length does not leave either."""
    assert W.shape("Sent to zorvex.quill@example.com") == "Sent to <email>"
    assert W.shape("Pay $1,204.55 now") == "Pay <amount> now"


def test_a_greeted_name_is_shaped_even_when_it_is_an_ordinary_word():
    assert W.shape("Welcome back, June Price") == "Welcome back, aaaa aaaaa"


def test_the_owners_name_is_shaped_wherever_it_stands():
    """June and Price are words on the list, and the owner's name is taken
    off it, alone, joined to another word or in an address."""
    set_private_words(["June Price"])
    assert W.shape("June Price") == "aaaa aaaaa"
    assert W.shape("junepayments") == "aaaaaaaaaaaa"
    assert W.shape("https://x.example/u/june/price") == \
        "https://a.example/a/aaaa/aaaaa"


def test_a_letter_alone_is_kept_and_an_initial_inside_a_name_is_not():
    assert W.shape("p") == "p"
    assert W.shape("%s Q %s" % (SURNAME, STREET)) == "aaaaaaaaaaa a aaaaaaaaaaaa"


def test_the_unit_that_ends_a_key_of_ours_is_kept_and_an_initial_is_not():
    """wait_s is seconds, after a word on the list. After a name the letter
    is shaped like the name."""
    assert W.shape("longest_wait_s") == "longest_wait_s"
    assert W.shape("%s_J" % SURNAME) == "aaaaaaaaaaa_a"


def test_a_contraction_reads_as_one():
    assert W.shape("Don't show this again") == "Don't show this again"
    assert W.shape("%s's documents" % SURNAME) == "aaaaaaaaaaa's documents"


def test_words_written_together_are_looked_for_in_lowercase_only():
    """An address or a key joins words in lowercase. A capitalized word is
    how a page writes a name, and Mayon read as may and on was a surname
    kept whole."""
    assert W.shape("myaccount") == "myaccount"
    assert W.shape("statementsandtaxes") == "statementsandtaxes"
    assert W.shape("statementsAndTaxes") == "statementsAndTaxes"
    assert W.shape("Mayon") == "aaaaa"


def test_an_id_of_letters_and_digits_keeps_no_short_word_inside_it():
    assert W.shape("AT4NO9QQ2KLMZ") == "aa9aa9aa9aaaa"


def test_a_random_id_almost_never_keeps_a_letter():
    """Twenty thousand invented ids of thirteen letters and digits. Kept
    whenever a short word turned up inside, one in twenty kept a few
    letters. With the rule for a short word inside an id, measured at two."""
    rng = random.Random(7)
    alphabet = string.ascii_uppercase + string.digits
    kept = 0
    for _ in range(20000):
        tok = "".join(rng.choice(alphabet) for _ in range(13))
        if set(W.shape(tok)) - {"a", "9"}:
            kept += 1
    assert kept <= 10, "%d of 20000 random ids kept some letters" % kept


def test_shaping_twice_changes_nothing():
    for text in ("Statement for %s" % SURNAME, MERCHANT + "-MSR-10000000000000.PDF",
                 "Welcome back, June Price", "Pay $1,204.55", "acct123Summary",
                 "https://x.example/merchant/%s?id=%s#/a/%s" % (LETTERS, MERCHANT, SURNAME),
                 "Don't", "%s's" % SURNAME, "p", "<email>", "a for a letter"):
        once = W.shape(text)
        assert W.shape(once) == once, text


# -- a file's name and an address -------------------------------------------------

def test_a_file_name_keeps_its_kind_in_lowercase_and_its_length():
    name = MERCHANT + "-MSR-10000000000000-20000000000000.PDF"
    got = W.shape_name(name)
    assert got == "aa9aaaaaa9aaa-aaa-99999999999999-99999999999999.pdf"
    assert len(got) == len(name)


def test_a_file_kind_not_on_the_list_is_a_word_like_any_other():
    assert W.shape_name("%s.%s" % (SURNAME, STREET)) == "aaaaaaaaaaa.aaaaaaaaaaaa"
    assert W.shape_name("statement_2031-02.pdf") == "statement_9999-99.pdf"


def test_an_address_is_shaped_part_by_part():
    url = ("https://%s:pw0400@%s.example.com:8443/merchant/%s/statements"
           "?merchantId=%s&reportType=standard#/acct/%s"
           % (SURNAME, LETTERS.lower(), LETTERS, MERCHANT, SURNAME))
    got = W.shape_url(url)
    assert got == ("https://aaaaaaaaaaaaa.example.com:9999/merchant/aaaaaaaaaaaaa/statements"
                   "?merchantId=aa9aaaaaa9aaa&reportType=standard#/acct/aaaaaaaaaaa")
    assert "pw" not in got, "the user and password before a host never leave"


def test_an_address_can_leave_without_its_query():
    assert W.shape_url("https://x.example/a?merchant=%s" % LETTERS, query=False) \
        == "https://x.example/a"


def test_the_apps_own_name_reads_as_itself():
    words = W.words_for("American Family", types.SimpleNamespace(__name__="amfam_site"))
    assert words == {"american", "family", "amfam"}
    assert W.shape_url("https://www.amfam.com/statements", words) == \
        "https://www.amfam.com/statements"


def test_the_apps_words_come_from_its_source_and_nothing_learned_at_run_time(tmp_path):
    """The hosts a site module lists are its own words, read from its source
    file. Golden 1 adds a vendor's host to the list when a tab opens, so
    what the module holds by then is partly a page's and is never read."""
    source = tmp_path / "zorvexbank_site.py"
    source.write_text('VENDOR = "docs.quillvendor.example"\n'
                      'ALLOWED_HOSTS = {"zorvexbank.com", VENDOR}\n', encoding="utf-8")
    site = types.SimpleNamespace(__name__="zorvexbank_site", __file__=str(source),
                                 ALLOWED_HOSTS={"zorvexbank.com", "docs.quillvendor.example",
                                                "%s.example.com" % LETTERS.lower()})
    words = W.words_for("Zorvex Bank", site)
    assert words == {"zorvex", "bank", "zorvexbank", "com", "docs", "quillvendor", "example"}
    assert LETTERS.lower() not in words


# -- a whole file ------------------------------------------------------------------

@dataclasses.dataclass
class Row:
    title: str
    amount: float


def test_a_file_is_rebuilt_from_what_may_leave():
    info = {
        "title": "Statements for %s" % SURNAME,
        MERCHANT: {"nested": ["%s holdings" % SURNAME.lower()]},
        "rows": [Row("February %s" % MERCHANT, 1204.55)],
        "count": 3, "total": 10 ** 9, "amount": 1204.55, "found": True, "none": None,
        "note": W.Fixed("Written by us, 0400 times."),
    }
    out = W.shape_tree(info)
    text = json.dumps(out)
    for canary in (SURNAME, MERCHANT, "1204"):
        assert canary.lower() not in text.lower(), canary
    assert out["title"] == "Statements for aaaaaaaaaaa"
    assert out["aa9aaaaaa9aaa"] == {"nested": ["aaaaaaaaaaa holdings"]}
    assert out["rows"] == [{"title": "February aa9aaaaaa9aaa", "amount": None}]
    assert (out["count"], out["total"], out["amount"]) == (3, 100000, None)
    assert out["found"] is True and out["none"] is None
    assert out["note"] == "Written by us, 0400 times."


def test_two_keys_of_one_shape_stay_two_keys():
    out = W.shape_tree({"88213344": 1, "77102233": 2})
    assert sorted(out.values()) == [1, 2]


def test_a_file_nested_beyond_all_reason_is_cut():
    """Beyond anything of ours, and well short of running out of stack."""
    deep = "x"
    for _ in range(300):
        deep = {"x": [deep]}
    assert "..." in json.dumps(W.shape_tree(deep))


def test_write_shaped_writes_what_shape_tree_builds(tmp_path):
    path = tmp_path / "out.json"
    W.write_shaped(path, {"title": SURNAME, "kind": "statement"})
    assert json.loads(path.read_text(encoding="utf-8")) == \
        {"title": "aaaaaaaaaaa", "kind": "statement"}


# -- the list ----------------------------------------------------------------------

def test_no_word_on_the_list_is_one_letter_or_capitalized():
    assert not [w for w in W.KNOWN if len(w) < 2 or w != w.lower()]


def test_the_list_holds_digits_only_in_names_of_things():
    """A word with digits in it is a tag, a version, a form or a class of
    answer, never a number off a page."""
    with_digits = {w for w in W.KNOWN if any(c.isdigit() for c in w)}
    assert with_digits <= {"form1099", "www2", "h1", "h2", "h3", "h4", "h5", "h6",
                           "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9",
                           "1xx", "2xx", "3xx", "4xx", "5xx"}


def _keys_and_words(tree):
    """Every string a module uses as a key, writes as a key or reads a key
    by, which is what its files are written in."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            out.update(k.value for k in node.keys
                       if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            out.add(node.slice.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "setdefault", "pop") and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            out.add(node.args[0].value)
    return out


def test_every_word_a_file_of_ours_is_written_in_comes_through_whole():
    """A key of ours that was not on the list would leave as its shape,
    and the sentence read from it would not be said. The journal's
    "watching" did, and a hidden list went unreported."""
    from paperpull_core import api_census, failure, journal, ready, recorder
    found = set()
    for name in ("recorder", "failure", "journal", "api_census", "identity", "ready",
                 "restore", "page_check"):
        found |= _keys_and_words(ast.parse(
            (CORE / "paperpull_core" / (name + ".py")).read_text(encoding="utf-8")))
    for values in (recorder.STRUCTURE_TAGS, recorder.STRUCTURE_ROLES,
                   recorder.STRUCTURE_ATTRS, failure.SAFE_TAGS, failure.SIGNAL_CLASSES,
                   failure._ROLES, failure._DISPLAY, failure._VISIBILITY,
                   failure._POSITION, failure._OVERFLOW, journal.PHASES,
                   journal.ROUTE_CHANGES, ready.STRATEGIES, ready.OUTCOMES,
                   api_census._METHODS, recorder._HOWS,
                   [k for k, _ in failure.ERROR_KINDS],
                   [k for k, _ in api_census._KINDS]):
        found |= {str(v) for v in values}
    changed = sorted(s for s in found if W.shape(s) != s)
    assert not changed, "these would leave as their shape: %s" % changed


def _entry_of(app):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and _entry_of(d))

# Each method an app names a step with, and where its words are. A press
# through paperpull_core.pressing names its step for the failure file too,
# and a stop the app raises itself names its step and its reason.
_STEPS = {"write_failure": ([0, 1], ("step", "reason")), "op": ([1], ("operation",)),
          "checkpoint": ([0], ("name",)), "result": ([0], ("outcome",)),
          "chose": ([0, 1], ("collection", "selector_id")), "waited": ([0], ("name",)),
          "click": ([], ("step",)), "check": ([], ("step",)),
          "Stop": ([0, 1], ("step", "reason")), "no_answer": ([0, 1], ("step", "reason"))}

# Calls whose keyword arguments are facts, a name and a value of the app's.
_FACTS = {"op", "result", "chose", "checkpoint", "waited", "_trace"}

# Where an app lays a whole dict of its own into a failure file.
_DICTS = ("extra", "postmortem")


def _strings(node):
    return [c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_word_an_app_writes_into_a_failure_file_comes_through(app):
    """The names in its FALLBACK table, the phrases it hands the journal and
    the failure file, the facts it records and what it adds to a trace are
    its own, written in its source, and a failure file is read by them.
    Missing from the list, Uber's "side" came out as "aaaa" and the
    sentence read from it was never said."""
    entry = _entry_of(app)
    tree = ast.parse(entry.read_text(encoding="utf-8"))
    provider = next((k.value.value for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and ast.unparse(n.func).endswith("write_survey")
                     for k in n.keywords if k.arg == "provider"
                     and isinstance(k.value, ast.Constant)), "")
    site_file = next(iter(sorted(app.glob("*_site.py"))), None)
    words = W.words_for(provider, types.SimpleNamespace(
        __name__=app.name + "_site", __file__=str(site_file) if site_file else None))
    found = []
    for path in [entry] + sorted(app.glob("*_site.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                    isinstance(t, ast.Name) and t.id == "FALLBACK" for t in node.targets):
                found += [k.value for k in node.value.keys
                          if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name in _STEPS:
                idxs, kws = _STEPS[name]
                args = [node.args[i] for i in idxs if i < len(node.args)]
                args += [k.value for k in node.keywords if k.arg in kws]
                found += [s for a in args for s in _strings(a)]
            if name in _FACTS:
                for k in node.keywords:
                    if k.arg:
                        found += [k.arg] + _strings(k.value)
            if name == "append" and "trace" in ast.unparse(node.func).lower() \
                    and node.args and isinstance(node.args[0], ast.Dict):
                found += _strings(node.args[0])
            for k in node.keywords:
                if k.arg in _DICTS and isinstance(k.value, ast.Dict):
                    found += _strings(k.value)
    changed = sorted({s for s in found if W.shape(s, words) != s})
    assert not changed, "%s would leave as their shape: %s" % (app.name, changed)


def test_every_word_a_press_writes_into_a_failure_file_comes_through():
    """paperpull_core.pressing names the step, the reason and the facts of
    every stop it raises, and an app writes them into the failure file. A
    word of them missing from the list would leave as its shape, as
    "covers" first did."""
    from paperpull_core import pressing
    tree = ast.parse((CORE / "paperpull_core" / "pressing.py").read_text(encoding="utf-8"))
    stops = {"Stop", "Covered", "Unread", "NotPressed", "NoAnswer", "no_answer"}
    found = set(pressing._WHY)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name in stops:
                found.update(a.value for a in node.args[:2]
                             if isinstance(a, ast.Constant) and isinstance(a.value, str))
                facts = node.args[3] if len(node.args) > 3 else None
                if isinstance(facts, ast.Dict):
                    found.update(k.value for k in facts.keys if isinstance(k, ast.Constant))
        if isinstance(node, ast.FunctionDef):
            pos = node.args.args
            pairs = list(zip(pos[len(pos) - len(node.args.defaults):], node.args.defaults))
            pairs += list(zip(node.args.kwonlyargs, node.args.kw_defaults))
            for arg, default in pairs:
                if arg.arg == "step" and isinstance(default, ast.Constant):
                    found.add(default.value)
    found |= {"tag", "role", "label"}
    assert {"something on the page is over the control", "over_it", "press a control"} <= found
    changed = sorted(s for s in found if W.shape(s) != s)
    assert not changed, "these would leave as their shape: %s" % changed


def test_is_shape_reads_a_shape_back():
    assert W.is_shape("aaaa") and W.is_shape("9999")
    assert not W.is_shape("a"), "a lone a is the word, as in Pay a bill"
    assert not W.is_shape("Statement") and not W.is_shape("aa9")


def test_the_module_says_what_may_leave():
    """Its docstring is what a reviewer checks the code against."""
    doc = W.__doc__
    for part in ("a for a letter", "9 for a digit", "Fixed", "words_for"):
        assert part in doc, part
    assert re.search(r"never because\s+one recording needed it", doc)
