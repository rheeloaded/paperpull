"""A card only the plural reads, beside cards and accounts that were always
read (#35), found by a second review before release.

The download step looked up the empty key as the first card in page order.
Once a card only the plural reads could come first, a Visa's statement was
looked for in the other card's history, and a statement of the same day was
saved as the Visa's. The index repair matched a row by its bare file name,
which a file in Manual Review, or a name freed by a deleted file, can share
with another account's, and Rename then gave that account's file the card's
name. Every date, heading and file here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
from paperpull_core import doc_types, renaming
from paperpull_core.models import State

import golden1_docs
import golden1_site as site
import test_accounts_and_pages as shaped
import test_a_card_heading_in_the_plural as T

PLURAL = T.PLURAL
VISA = T.VISA


def test_the_empty_key_finds_the_panel_that_holds_it():
    panels = [{"i": 0, "heading": "Member Statements"}, {"i": 1, "heading": PLURAL},
              {"i": 2, "heading": VISA}]
    site._assign_kinds(panels)
    member, plural, visa = panels
    assert visa["card"] and visa["account_key"] == ""
    assert site._panel_for(panels, "Credit Card Statement - August 20, 2025", "") is visa
    assert site._panel_for(panels, "Credit Card Statement - August 20, 2025", T.OWN) is plural
    assert site._panel_for(panels, "Account Statement - August 31, 2025", "") is member
    assert site._panel_for(panels, "Credit Card Statement - August 20, 2025", "nobody") is None


def test_a_panel_read_elsewhere_is_found_by_its_place_as_before():
    panels = [{"i": 0, "heading": "Member Statements", "card": False},
              {"i": 1, "heading": VISA, "card": True}]
    assert site._panel_for(panels, "Credit Card Statement - August 20, 2025", "") is panels[1]
    assert site._panel_for(panels, "Account Statement - August 31, 2025", "") is panels[0]


# The vendor test_accounts_and_pages makes up, its card under the plural
# heading, and a Visa after it with statements of its own on the same days.
_THIRD = """  <div class="panel">
   <h2 aria-expanded="false" class="head" data-a="1" data-b="2">%s</h2>
   <div class="body" id="p2" style="display:none"><ul><li><h3 id="h2">Visa Signature</h3>
     <ul><li><a href="#">Current Statement</a></li>
         <li><div><a href="#" class="hist" data-panel="2" target="_blank">Statement History</a></div></li>
         <li><a href="#">Make a payment</a></li></ul></li></ul></div>
  </div>
 </div>
 <div id="dlg\"""" % VISA
_VENDOR = (shaped.VENDOR
           .replace("VISA SIGNATURE CARD ****4321", PLURAL, 1)
           .replace(' </div>\n <div id="dlg"', _THIRD, 1)
           .replace("const LISTS = {0: ",
                    "const LISTS = {2: %s, 0: " % str(shaped._twentieths(15)).replace("'", '"'), 1)
           .replace("(panel ? 'card' : 'member')", "('panel' + panel)", 1))


@pytest.fixture()
def vendor(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    pg.set_content(_VENDOR)
    monkeypatch.setattr(site, "goto_documents", lambda page: True)
    monkeypatch.setattr(site, "open_vendor", lambda page: pg)
    yield pg
    browser.close()
    driver.stop()


def test_the_page_holds_both_cards(vendor):
    assert PLURAL in _VENDOR and VISA in _VENDOR and 'data-panel="2"' in _VENDOR
    docs = site.collect_download_docs(vendor, trace=[])
    visa = [d for d in docs if d.title.startswith(site.CARD_TITLE) and d.account == ""]
    plural = [d for d in docs if d.title.startswith(site.CARD_TITLE) and d.account == T.OWN]
    assert len(visa) == 15 and len(plural) == 15, (len(visa), len(plural))


def test_the_visas_statement_is_saved_from_the_visas_own_panel(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out,
                              title="Credit Card Statement - August 20, 2025",
                              account="", trace=trace), trace
    assert b"invented panel2 statement 08/20/25" in out.read_bytes()


def test_the_plural_cards_statement_is_saved_from_its_own_panel(vendor, tmp_path):
    out = tmp_path / "s.pdf"
    trace: list = []
    assert site.download_bill(vendor, tmp_path / "dl", "2025-08-20", out,
                              title="Credit Card Statement - August 20, 2025",
                              account=T.OWN, trace=trace), trace
    assert b"invented panel1 statement 08/20/25" in out.read_bytes()


# -- the index repair takes only its own row -------------------------------------

D = "2026-08-20"


def _saved(app, folder, title, account, heading, state=State.COMPLETED.value, ok=True):
    """One record, index row and file, as 0.41.0 leaves them."""
    category, summary, conf = doc_types.classify_document(title, app.rules)
    doc = golden1_docs.Document(title=title, category=category, summary=summary,
                                date=D, confidence=conf, account=account)
    rec = doc.to_dict()
    name = storage.build_pdf_filename(D, summary, "", record=rec)
    path = storage.unique_path(folder, name)
    path.write_bytes(b"%PDF-1.7 " + heading.encode() + b" " + D.encode())
    rec.update(state=state, downloaded_ok=ok, pdf_filename=path.name, pdf_path=str(path))
    app.index_csv.append_rows([{
        "Document Date": D, "Category": category, "Document Summary": summary,
        "Document Title": title, "PDF Filename": path.name, "PDF Full Path": str(path),
        "Processing Status": "Completed" if ok else "Needs Manual Review"}])
    app.progress.data[doc.key] = dict(rec)
    app.discovery.data[doc.key] = dict(rec)
    return path


def test_a_checking_file_sharing_the_cards_file_name_keeps_its_own_name(tmp_path, monkeypatch):
    """The card's statement went to Manual Review under the base name, and
    checking's of the same day took the same base name in Statements."""
    statements, review = tmp_path / "Statements", tmp_path / "Manual Review"
    statements.mkdir()
    review.mkdir()
    app = T.make_app(tmp_path)
    card_file = _saved(app, review, "Account Statement - August 20, 2026", T.OWN, PLURAL,
                       state=State.NEEDS_MANUAL_REVIEW.value, ok=False)
    checking_file = _saved(app, statements, "Account Statement - August 20, 2026", "",
                           T.CHECKING)
    assert card_file.name == checking_file.name
    app.discovery.save()
    app.progress.save()
    T.discover(app, T.raw_docs(T.now(T.CHECKING, PLURAL), {0: [D], 1: [D]}), monkeypatch)
    renaming.run_for(app, apply_changes=True, say=lambda *_: None)
    for p in statements.iterdir():
        assert "Credit Card" not in p.name or T.whose(p) == PLURAL, p.name
    rows = {r["PDF Full Path"]: r["Document Title"] for r in app.index_csv.read_all()}
    assert rows[str(checking_file)] == "Account Statement - August 20, 2026", rows


def test_a_name_freed_by_a_deleted_file_is_never_taken_for_the_cards(tmp_path, monkeypatch):
    """The member deletes each file once paperless has it. The card's file of
    that day is gone, checking's of the same day arrives later under the
    freed name, and no later Discover retitles checking's row."""
    statements = tmp_path / "Statements"
    statements.mkdir()
    app = T.make_app(tmp_path)
    card_file = _saved(app, statements, "Account Statement - August 20, 2026", T.OWN, PLURAL)
    app.discovery.save()
    app.progress.save()
    T.discover(app, T.raw_docs(T.now(T.CHECKING, PLURAL), {1: [D]}), monkeypatch)
    card_file.unlink()
    again = T.make_app(tmp_path)
    checking_file = _saved(again, statements, "Account Statement - August 20, 2026", "",
                           T.CHECKING)
    assert checking_file == card_file
    again.discovery.save()
    again.progress.save()
    third = T.make_app(tmp_path)
    T.discover(third, T.raw_docs(T.now(T.CHECKING, PLURAL), {0: [D], 1: [D]}), monkeypatch)
    titles = sorted(r["Document Title"] for r in third.index_csv.read_all()
                    if r["PDF Full Path"] == str(checking_file))
    assert titles == ["Account Statement - August 20, 2026",
                      "Credit Card Statement - August 20, 2026"], titles


def test_a_repair_whose_mark_was_lost_still_takes_no_later_row(tmp_path, monkeypatch):
    """The row was put right and the mark on the record could not be saved.
    The record's row already carries the new title, so it counts as put
    right, and checking's later row under the freed name is left alone."""
    statements = tmp_path / "Statements"
    statements.mkdir()
    app = T.make_app(tmp_path)
    card_file = _saved(app, statements, "Account Statement - August 20, 2026", T.OWN, PLURAL)
    app.discovery.save()
    app.progress.save()
    T.discover(app, T.raw_docs(T.now(T.CHECKING, PLURAL), {1: [D]}), monkeypatch)
    lost = T.make_app(tmp_path)
    for rec in lost.progress.data.values():
        rec.pop("index_carried", None)
    lost.progress.save()
    card_file.unlink()
    checking_file = _saved(lost, statements, "Account Statement - August 20, 2026", "",
                           T.CHECKING)
    lost.discovery.save()
    lost.progress.save()
    third = T.make_app(tmp_path)
    T.discover(third, T.raw_docs(T.now(T.CHECKING, PLURAL), {0: [D], 1: [D]}), monkeypatch)
    titles = sorted(r["Document Title"] for r in third.index_csv.read_all()
                    if r["PDF Full Path"] == str(checking_file))
    assert titles == ["Account Statement - August 20, 2026",
                      "Credit Card Statement - August 20, 2026"], titles
