"""Two accounts of the same product do not share one document's identity.

A document is remembered by category, date, title and account, and the
account was cut to forty characters. Two cards of the same product are named
identically until the masked last four at the end, so both produced the same
key. The second card's whole history was read as already downloaded and
dropped, on every run, and nothing anywhere said so. That memory is
permanent by design, so the loss was too.

Chase found it and fixed it in Chase, in 0.17.1. Thirty-two other apps kept
the forty characters, and the labels that overrun them are in this
repository's own fixtures: "U.S. Bank Cash+ Visa Signature Card (...1234)"
is forty-five characters long.

The key only moves for an account long enough to have been cut, so an
archive of short names is untouched, and the rest are carried over the first
time the app runs. Both halves are checked here.
"""
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))

# Long enough that the last four falls past the cut, which is the whole case.
PAIRS = [
    ("U.S. Bank Cash+ Visa Signature Card (...1234)",
     "U.S. Bank Cash+ Visa Signature Card (...5678)"),
    ("Triple Cash Rewards World Elite Mastercard ...7890",
     "Triple Cash Rewards World Elite Mastercard ...4321"),
    ("MARRIOTT BONVOY BOUNDLESS CREDIT CARD (...1234)",
     "MARRIOTT BONVOY BOUNDLESS CREDIT CARD (...5678)"),
    ("Premier Checking Account for Household Members ****1111",
     "Premier Checking Account for Household Members ****2222"),
]


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def document_class(app: Path):
    mod = load(app)
    cls = getattr(mod, "Document", None)
    if cls is None:
        pytest.skip("a receipts app, whose identity is the order number")
    return mod, cls


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_two_accounts_of_the_same_product_are_different_documents(app):
    _mod, Document = document_class(app)
    if app.name in ("affirm", "fairfaxwater", "fidelity", "netbenefits",
                    "tsp", "wealthfront"):
        pytest.skip("its key carries no account at all, which is its own question")
    for one, two in PAIRS:
        a = Document(category="Statement", date="2026-03-31",
                     title="Statement", account=one)
        b = Document(category="Statement", date="2026-03-31",
                     title="Statement", account=two)
        assert a.key != b.key, (
            "%s gives the same key to %r and %r, so one of them is dropped"
            % (app.name, one[-12:], two[-12:]))


def uses_the_account(Document) -> bool:
    marker = "ZZQQ"
    return marker in Document(category="Statement", date="2026-03-31",
                              title="Statement", account=marker).key


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_an_account_that_always_fitted_keeps_the_key_it_had(app):
    """The other half, and the reason this is safe to ship. A key that
    changes underneath an archive makes every document in it look new, so
    they are all downloaded again beside the copies already there.

    An account short enough to have survived the cut must appear in the key
    whole, exactly as it did before, with nothing added after it.
    """
    _mod, Document = document_class(app)
    if not uses_the_account(Document):
        pytest.skip("its key carries no account")
    from paperpull_core.storage import sanitize_component
    for account in ("Checking", "Freedom Unlimited (...1234)",
                    "Kids Savings Account (...5678)"):
        key = Document(category="Statement", date="2026-03-31",
                       title="Statement", account=account).key
        assert sanitize_component(account) in key, (
            "%s no longer carries a short account whole: %s" % (app.name, key))


# -- carrying an existing archive over -----------------------------------------

def legacy_key(Document, account: str) -> str:
    """The key this record would have been written under before the fix."""
    from paperpull_core.keys import account_component
    from paperpull_core.storage import sanitize_component
    raw = sanitize_component(account)
    doc = Document(category="Statement", date="2026-03-31",
                   title="Statement", account=account)
    return doc.key.replace(account_component(raw), raw[:40])


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_record_under_the_old_key_is_moved_across(app):
    mod, Document = document_class(app)
    migrate = getattr(mod, "migrate_legacy_keys", None)
    if migrate is None:
        pytest.skip("this app's key never carried a cut account")
    account = "U.S. Bank Cash+ Visa Signature Card (...1234)"
    doc = Document(category="Statement", date="2026-03-31",
                   title="Statement", account=account)
    record = doc.to_dict()
    record["downloaded_ok"] = True
    old_key = legacy_key(Document, account)
    assert old_key != doc.key
    records = {old_key: record}

    assert migrate(records) == 1
    assert old_key not in records
    assert records[doc.key]["downloaded_ok"] is True


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_finished_record_is_never_replaced_by_an_unfinished_one(app):
    """Both cards may already have records. Moving one must not mark the
    other's documents as done, which is the failure this is guarding."""
    mod, Document = document_class(app)
    migrate = getattr(mod, "migrate_legacy_keys", None)
    if migrate is None:
        pytest.skip("this app's key never carried a cut account")
    account = "U.S. Bank Cash+ Visa Signature Card (...1234)"
    doc = Document(category="Statement", date="2026-03-31",
                   title="Statement", account=account)
    finished = doc.to_dict()
    finished["downloaded_ok"] = True
    fresh = doc.to_dict()
    fresh["downloaded_ok"] = False

    records = {legacy_key(Document, account): fresh, doc.key: finished}
    migrate(records)
    assert records[doc.key]["downloaded_ok"] is True


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_key_this_did_not_write_is_left_where_it_is(app):
    mod, _Document = document_class(app)
    migrate = getattr(mod, "migrate_legacy_keys", None)
    if migrate is None:
        pytest.skip("this app's key never carried a cut account")
    records = {"something:else:entirely": {"category": "Statement"},
               "id:1234-abcd": {"category": "Statement", "document_id": "x"}}
    before = dict(records)
    migrate(records)
    assert records == before


def test_the_component_itself():
    from paperpull_core.keys import account_component as short
    assert short("Checking") == "Checking"
    assert short("") == ""
    forty = "x" * 40
    assert short(forty) == forty
    long_one = "U.S. Bank Cash+ Visa Signature Card (...1234)"
    assert short(long_one) == long_one[:40] + "-1234"
    assert short(long_one) != short(long_one.replace("1234", "5678"))
    # nothing to keep, so nothing is added
    no_digits = "A very long account name with no digits at the end"
    assert short(no_digits) == no_digits[:40]
