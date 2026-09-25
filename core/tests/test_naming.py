"""File names from a pattern (#50), and the promise that nothing changes.

Two things are held here. The pattern language does what docs/file-naming.md
says, every example from #50 included, and it refuses a bad pattern with a
message a person can act on. And the default patterns reproduce every name
exactly as it was built before patterns existed, because an upgrade that
renamed somebody's archive would be the worst way to introduce this.
"""
import itertools
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import naming, storage  # noqa: E402
from paperpull_core.spec import DOCUMENT, RECEIPT, AppSpec  # noqa: E402


# -- the language --------------------------------------------------------------

FIELDS = {"date": "2026-09-23", "provider": "Amazon", "number": "112-7124528-9515453",
          "summary": "Computer Accessories", "kind": "Receipt", "owner": "",
          "account": "", "year": "2026", "month": "09"}


@pytest.mark.parametrize("pattern,expected", [
    # the three from the issue
    ("{date:yyyymmdd} - {provider} -- {number}", "20260923 - Amazon -- 112-7124528-9515453"),
    ("{date:yyyy-mm-dd} {provider} {summary} {kind}",
     "2026-09-23 Amazon Computer Accessories Receipt"),
    ("{date:yyyy-mm-dd}_000000 {provider}", "2026-09-23_000000 Amazon"),
    # dates
    ("{date:dd mmm yyyy}", "23 Sep 2026"),
    ("{date:mmmm d, yy}", "September 23, 26"),
    ("{year}/{month}", "2026/09"),
    ("{date}", "2026-09-23"),
])
def test_what_a_pattern_writes(pattern, expected):
    assert naming.render(pattern, FIELDS) == expected


def test_an_optional_section_takes_its_separators_with_it():
    """A provider with no order number must not leave "Acme -- " with
    nothing after it, which was the objection to plain placeholders."""
    p = "{date:yyyymmdd}[ - {provider}][ -- {account}]"
    assert naming.render(p, FIELDS) == "20260923 - Amazon"


def test_the_first_field_with_a_value_is_used():
    """jpfieber's if/elif example on #50, without writing any logic."""
    p = "{date:yyyymmdd}[ - {provider}][ -- {account|number|kind}]"
    assert naming.render(p, FIELDS) == "20260923 - Amazon -- 112-7124528-9515453"
    assert naming.render(p, dict(FIELDS, number="")) == "20260923 - Amazon -- Receipt"


def test_sections_can_hold_sections():
    p = "{date:yyyymmdd}[ ({provider}[ {account}])]"
    assert naming.render(p, FIELDS) == "20260923 (Amazon)"


def test_a_bracket_or_brace_can_be_written_as_itself():
    assert naming.render(r"\[{provider}\] \{x\}", FIELDS) == "[Amazon] {x}"


@pytest.mark.parametrize("pattern,says", [
    ("", "empty"),
    ("{date} {merchant}", 'no field called "merchant"'),
    ("{date:yyyy} {summary:upper}", "only a date can have a format"),
    ("{date:qq}", "has none of yyyy"),
    ("{date} [{provider}", "[ is never closed"),
    ("{date} {provider", "{ is never closed"),
    ("{date}] x", "] with no ["),
    ("just words", "names no field"),
    ("{{ date }}", "kept for a later template mode"),
    ("{date|}", "a field with no name"),
])
def test_a_bad_pattern_says_what_is_wrong_and_where(pattern, says):
    problem = naming.check(pattern)
    assert problem and says in problem
    if pattern:
        assert re.search(r"at character \d+", problem)


def test_a_date_that_is_not_a_date_is_written_as_it_is():
    assert naming.render("{date:yyyymmdd}", {"date": "0000-00-00"}) == "0000-00-00"
    assert naming.render("{date:yyyymmdd}", {"date": "unknown"}) == "unknown"


# -- the promise that nothing changes -------------------------------------------

def _old_build(provider, purchase_date, summary, document_type="Receipt",
               part=None, owner=""):
    """build_pdf_filename exactly as it was before patterns, kept here as
    the reference the defaults are held to."""
    date = (purchase_date or "0000-00-00").strip()
    summary = storage.title_case(summary or "Purchase")
    who = f"{owner.strip()} " if owner and owner.strip() else ""
    base = f"{date} {who}{provider} {summary} {document_type}"
    if part and part[1] > 1:
        base += f" ({part[0]} of {part[1]})"
    return storage.sanitize_component(base) + ".pdf"


class _Record:
    """A record carrying every field a pattern could reach for, so the
    defaults are shown not to reach for any of them."""
    category = "Statement"
    document_type = "Invoice"
    order_number = "112-7124528-9515453"
    account = "Checking ...1234"
    total = "$12.00"


DATES = ["2026-09-23", "", " 2026-01-02 ", "0000-00-00", "2026-13-40", "Sep 2026"]
SUMMARIES = ["", "monthly statement", "Children's clothing and toys",
             "A: b/c * d? <e> |f|", "the end of the world", "x" * 300,
             "  spaced   out  ", "CON", "trailing dots..."]
TYPES = ["Receipt", "Invoice", "", "Tax Document"]
PARTS = [None, (1, 1), (2, 3)]
OWNERS = ["", "Jane Q", "  "]


@pytest.mark.parametrize("kind", [RECEIPT, DOCUMENT])
def test_the_default_pattern_reproduces_every_old_name(kind, tmp_path, monkeypatch):
    spec = AppSpec(provider="Acme Co", project_dir=tmp_path, kind=kind)
    monkeypatch.setattr(storage, "_SPEC", spec)
    monkeypatch.setattr(storage, "_FILENAME_PATTERN", "")
    checked = 0
    for d, s, t, p, o in itertools.product(DATES, SUMMARIES, TYPES, PARTS, OWNERS):
        for record in (None, _Record(), {"category": "Tax Document"}):
            new = storage.build_pdf_filename(d, s, t, part=p, owner=o,
                                             record=record)
            assert new == _old_build("Acme Co", d, s, t, p, o), (d, s, t, p, o)
            checked += 1
    assert checked > 5000


def test_a_config_pattern_is_used_and_a_broken_one_falls_back(tmp_path, monkeypatch,
                                                               capsys):
    spec = AppSpec(provider="Acme", project_dir=tmp_path, kind=RECEIPT)
    monkeypatch.setattr(storage, "_SPEC", spec)
    monkeypatch.setattr(storage, "_PATTERN_WARNED", set())
    storage.set_filename_patterns(
        {"filename_pattern_receipts": "{date:yyyymmdd} - {provider}[ -- {number}]"})
    assert storage.build_pdf_filename("2026-09-23", "x", record=_Record()) == \
        "20260923 - Acme -- 112-7124528-9515453.pdf"
    storage.set_filename_patterns({"filename_pattern_receipts": "{date} {merchant}"})
    assert storage.build_pdf_filename("2026-09-23", "x") == \
        _old_build("Acme", "2026-09-23", "x")
    assert 'no field called "merchant"' in capsys.readouterr().out
    storage.set_filename_patterns({})


def test_an_apps_own_pattern_wins_and_the_other_kind_is_ignored(tmp_path, monkeypatch):
    spec = AppSpec(provider="Acme", project_dir=tmp_path, kind=DOCUMENT)
    monkeypatch.setattr(storage, "_SPEC", spec)
    cfg = {"filename_pattern_receipts": "{provider} receipt {date}",
           "filename_pattern_statements": "{provider} statement {date}"}
    assert storage.set_filename_patterns(cfg) == "{provider} statement {date}"
    cfg["filename_pattern"] = "{date} only"
    assert storage.set_filename_patterns(cfg) == "{date} only"
    storage.set_filename_patterns({})


def test_a_pattern_for_statements_reaches_the_records_own_fields(tmp_path, monkeypatch):
    spec = AppSpec(provider="Chase", project_dir=tmp_path, kind=DOCUMENT)
    monkeypatch.setattr(storage, "_SPEC", spec)
    name = storage.build_pdf_filename(
        "2026-08-31", "Statement", "", record=_Record(),
        pattern="{date:yyyymmdd} {provider}[ {account}] {kind}")
    assert name == "20260831 Chase Checking ...1234 Statement.pdf"


# -- every app hands over its record ---------------------------------------------

REPO = Path(__file__).resolve().parents[2]
APP_FILES = sorted(p for p in (REPO / "apps").glob("*/*.py"))


def _calls(path):
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(
                node.func, "id", getattr(node.func, "attr", "")) == "build_pdf_filename":
            yield node


def test_there_are_filename_calls_to_check():
    assert sum(1 for p in APP_FILES for _ in _calls(p)) >= 70


@pytest.mark.parametrize("path", APP_FILES, ids=lambda p: "%s/%s" % (p.parent.name, p.name))
def test_every_filename_is_built_with_its_record(path):
    """A pattern can only use a field the builder is handed. Every call
    passed the date, the summary and the kind alone, so an order number
    or an account in a pattern would have been empty in every app."""
    for call in _calls(path):
        assert any(k.arg == "record" for k in call.keywords), (
            "%s:%d names a file without handing over its record"
            % (path.name, call.lineno))


# -- what the settings page leans on ----------------------------------------------

def test_owner_in_a_pattern_of_your_own_is_the_configured_owner(tmp_path, monkeypatch):
    """Under the default the owner's name appears only when
    owner_in_filename is on, as it always has. Somebody who writes
    {owner} into a pattern wants it whatever that switch says."""
    spec = AppSpec(provider="Acme", project_dir=tmp_path, kind=RECEIPT)
    monkeypatch.setattr(storage, "_SPEC", spec)
    monkeypatch.setattr(storage, "_FILENAME_OWNER", "")
    storage.set_filename_patterns({"owner": "Jane",
                                   "filename_pattern_receipts": "{owner} {date}"})
    assert storage.build_pdf_filename("2026-09-23", "x") == "Jane 2026-09-23.pdf"
    storage.set_filename_patterns({"owner": "Jane"})
    assert storage.build_pdf_filename("2026-09-23", "x") == \
        _old_build("Acme", "2026-09-23", "x"), "the default stays as it was"
    storage.set_filename_patterns({})


def test_a_preview_is_the_name_a_run_would_build(tmp_path, monkeypatch):
    record = {"purchase_date": "2026-09-23", "summary": "computer accessories",
              "order_number": "112-7124528-9515453", "document_type": "Receipt"}
    pattern = "{date:yyyymmdd} - {provider}[ -- {number}] {summary}"
    spec = AppSpec(provider="Amazon", project_dir=tmp_path, kind=RECEIPT)
    monkeypatch.setattr(storage, "_SPEC", spec)
    built = storage.build_pdf_filename(record["purchase_date"], record["summary"],
                                       "Receipt", record=record, pattern=pattern)
    shown = naming.preview(pattern, record, provider="Amazon", receipts=True,
                           document_type="Receipt")
    assert shown == built == \
        "20260923 - Amazon -- 112-7124528-9515453 Computer Accessories.pdf"


def test_fill_rates_count_and_never_carry_a_value():
    records = [{"date": "2026-01-31", "account": "Checking CANARY 1234",
                "category": "Statement"},
               {"date": "2026-02-28", "account": "", "category": "Statement"}]
    got = naming.fill_rates(records)
    assert got["records"] == 2
    assert got["filled"]["account"] == 1 and got["filled"]["date"] == 2
    assert "CANARY" not in str(got)
