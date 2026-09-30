"""Kroger, from the pre-release review of 0.41.0 (#41).

A fresh reviewer ran the real code and found these before release. Resume
works from the purchase list without refreshing it, and a list from 0.40
names the store "In-Store", which Rename read over the banner in the record,
so Resume then Rename renamed good receipts back to "In-Store". The order
history cleanup could delete a purchase's only rows. A preview cut short
kept what it had read. And a few readings of the page went wrong. Every
number, store and item here is invented."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage
import kroger_receipts as kr
import kroger_site as site
from paperpull_core import renaming
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, Purchase, State

from test_banner_and_items import BODY, HEADER, PATTERN, _app, _text_pdf

NUMBER = "540~00123~2026-09-20~101~1234567"


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield
    core_storage.set_filename_patterns({})


def _saved(app, store_lines, progress_store="In-Store", read=False, discovery_store="In-Store",
           name="2026-09-20 Kroger Groceries Receipt.pdf"):
    """A receipt saved and recorded, the way a run leaves one."""
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    path = folder / name
    _text_pdf(path, HEADER[1:] + store_lines + BODY[:3])
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=NUMBER,
                 summary="Groceries", store_info=progress_store, pdf_filename=path.name,
                 pdf_path=str(path), state=State.COMPLETED.value)
    app.progress.update(p.key, dict(p.to_dict(), downloaded_ok=True, store_read=read))
    app.discovery.update(p.key, dict(p.to_dict(), store_info=discovery_store))
    app.index_csv.append_rows([{
        "Purchase Date": "2026-09-20", "Purchase Type": IN_STORE,
        "Order or Receipt Number": NUMBER, "Purchase Summary": "Groceries",
        "Document Type": "Receipt", "PDF Filename": path.name, "PDF Full Path": str(path),
        "Processing Status": "Completed"}])
    return p, folder


def _pdfs(folder):
    return sorted(f.name for f in folder.glob("*.pdf"))


# -- blocker one, the list's old label over the banner ---------------------------------

def test_resume_then_rename_keeps_the_banner(tmp_path):
    """Resume read the banner into the record and the list kept 0.40's
    In-Store, which Rename reads over the record."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    p, folder = _saved(app, ["Metro Market", "100 Example Rd"], progress_store="Metro Market",
                       read=True, discovery_store="In-Store",
                       name="2026-09-20 Metro Market Groceries Receipt.pdf")
    app.cmd_rename()
    assert _pdfs(folder) == ["2026-09-20 Metro Market Groceries Receipt.pdf"]
    assert app.discovery.get(p.key)["store_info"] == "Metro Market"


def test_resume_drops_an_unread_store_before_the_receipt_is_read(tmp_path):
    """A purchase made from 0.40's list says In-Store until its receipt is
    read, and a receipt naming no store leaves it with none, not In-Store."""
    app = _app(tmp_path)
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=NUMBER,
                 store_info="In-Store")
    app.discovery.update(p.key, dict(p.to_dict()))
    app._forget_unread_store(p)
    assert p.store_info == ""
    # once read, the record and the list both say so
    p.store_info = "Metro Market"
    app._note_store(p)
    assert app.discovery.get(p.key)["store_info"] == "Metro Market"
    assert app.discovery.get(p.key)["store_read"] is True
    q = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=NUMBER,
                 store_info="whatever the list said")
    app._forget_unread_store(q)
    assert q.store_info == "Metro Market"


def test_an_old_label_with_no_banner_in_the_pdf_becomes_the_provider(tmp_path):
    """Where the saved PDF names no store, a {store|provider} pattern falls
    back to Kroger, never to 0.40's In-Store."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    p, folder = _saved(app, ["100 Example Rd"], name="2026-09-20 In-Store Groceries Receipt.pdf")
    app.cmd_rename()
    assert _pdfs(folder) == ["2026-09-20 Kroger Groceries Receipt.pdf"]
    assert app.progress.get(p.key)["store_info"] == ""



def test_review_names_never_names_the_old_label_as_the_store(tmp_path, monkeypatch):
    """Review names built the name from the record as it was, and 0.40
    wrote the purchase type or Pickup where the store goes, so a receipt
    renamed there before any Rename took In-Store for its store (second
    review of 0.41.0)."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    p, folder = _saved(app, ["Northside Grocers", "100 Example Rd"], progress_store="Pickup",
                       name="2026-09-20 Kroger Mixed Purchases Receipt.pdf")
    app.index_csv.rewrite([dict(r, **{"Classification Confidence": "Low"})
                           for r in app.index_csv.read_all()])
    monkeypatch.setattr(kr, "ask", lambda prompt: "snacks")
    app.cmd_review_names()
    assert _pdfs(folder) == ["2026-09-20 Kroger Snacks Receipt.pdf"]


def test_review_names_names_a_store_read_off_the_receipt(tmp_path, monkeypatch):
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    p, folder = _saved(app, ["Metro Market", "100 Example Rd"], progress_store="Metro Market",
                       read=True, name="2026-09-20 Metro Market Mixed Purchases Receipt.pdf")
    app.index_csv.rewrite([dict(r, **{"Classification Confidence": "Low"})
                           for r in app.index_csv.read_all()])
    monkeypatch.setattr(kr, "ask", lambda prompt: "snacks")
    app.cmd_review_names()
    assert _pdfs(folder) == ["2026-09-20 Metro Market Snacks Receipt.pdf"]


def test_a_receipt_page_that_fails_twice_keeps_the_store_already_read(tmp_path, monkeypatch):
    """A run stopped after the banner was read and before the list was told
    leaves the list saying In-Store. A Resume whose page then failed twice
    wrote In-Store over the store read, still marked as read (second review
    of 0.41.0)."""
    app = _app(tmp_path)
    app.stats = {"mode": "", "manual_review": 0}
    app.write_failure = lambda *a, **k: None
    p = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-20", order_number=NUMBER,
                 store_info="Fred Meyer", state=State.DETAILS_EXTRACTED.value)
    app.progress.update(p.key, dict(p.to_dict(), store_read=True))
    app.discovery.update(p.key, dict(p.to_dict(), store_info="In-Store"))
    from_the_list = Purchase.from_dict(app.discovery.get(p.key))
    assert from_the_list.store_info == "In-Store"

    def fails(page, purchase):
        raise RuntimeError("the page did not load")
    monkeypatch.setattr(site, "goto_receipt", fails)
    monkeypatch.setattr(site, "goto_orders", lambda page, *a, **k: None)
    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    app.process_one(SimpleNamespace(url="https://www.kroger.com/mypurchases"), from_the_list)
    assert app.progress.get(p.key)["state"] == State.NEEDS_MANUAL_REVIEW.value
    assert app.progress.get(p.key)["store_info"] == "Fred Meyer"
    assert app._store_kept(p.key) == "Fred Meyer"


# -- blocker two, a purchase's only rows ------------------------------------------------

def test_a_purchase_whose_only_rows_were_summary_lines_keeps_one_blank_row(tmp_path, capsys):
    """0.40 wrote only the two summary lines for a receipt whose real items
    it refused, a gift card alone. Taking both out took the purchase out of
    the Purchases workbook."""
    app = _app(tmp_path)
    rows = [{"Order or Receipt Number": "A", "Item Name": n, "Order Total": "$21.48"}
            for n in ("Original Item Total", "Order Total", "Kroger Tortilla Chips, 13 oz")]
    rows += [{"Order or Receipt Number": "B", "Item Name": n, "Order Total": "$25.00"}
             for n in ("Original Item Total", "Order Total")]
    app.order_csv.append_rows(rows)
    app._clean_order_history(apply=True)
    left = app.order_csv.read_all()
    assert [(r["Order or Receipt Number"], r["Item Name"]) for r in left] == [
        ("A", "Kroger Tortilla Chips, 13 oz"), ("B", "")]
    assert [r["Order Total"] for r in left] == ["$21.48", "$25.00"]
    assert "Took 4 Order Summary line" in capsys.readouterr().out


def test_an_order_history_that_cannot_be_read_is_left_alone(tmp_path, capsys):
    app = _app(tmp_path)
    app.paths.order_history_csv.write_bytes("Item Name\r\nKroger\xae Chips\r\n".encode("cp1252"))
    before = app.paths.order_history_csv.read_bytes()
    app._clean_order_history(apply=True)
    assert "could not be read" in capsys.readouterr().out
    assert app.paths.order_history_csv.read_bytes() == before


# -- a preview changes nothing, however it ends ------------------------------------------------

@pytest.mark.parametrize("where", ["reading the second PDF", "renaming"])
def test_a_preview_cut_short_puts_everything_back(tmp_path, monkeypatch, where):
    """Ctrl+C partway, or an error, and the run's own finally saves both
    stores. What the preview changed is put back first, wherever it stopped."""
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    app.args.apply = False
    p, folder = _saved(app, ["Fred Meyer", "100 Example Rd"])
    q = Purchase(purchase_type=IN_STORE, purchase_date="2026-09-21", order_number=NUMBER + "9",
                 summary="Groceries", store_info="In-Store",
                 pdf_path=str(folder / "second.pdf"), state=State.COMPLETED.value)
    _text_pdf(folder / "second.pdf", HEADER[1:] + ["Ralphs"] + BODY[:3])
    app.progress.update(q.key, dict(q.to_dict(), downloaded_ok=True))
    app.discovery.update(q.key, dict(q.to_dict()))
    before = {k: (dict(app.progress.get(k)), dict(app.discovery.get(k))) for k in (p.key, q.key)}

    if where == "renaming":
        def cut_short(*a, **k):
            raise KeyboardInterrupt
        monkeypatch.setattr(renaming, "run_for", cut_short)
    else:
        real, calls = kr.receipt_pdf.pdf_text, []

        def cut_short(path):
            calls.append(path)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(path)
        monkeypatch.setattr(kr.receipt_pdf, "pdf_text", cut_short)
    with pytest.raises(KeyboardInterrupt):
        app.cmd_rename()
    assert {k: (app.progress.get(k), app.discovery.get(k)) for k in (p.key, q.key)} == before


def test_a_preview_puts_back_exactly_a_key_that_was_not_there(tmp_path):
    core_storage.set_filename_patterns({"filename_pattern": PATTERN})
    app = _app(tmp_path)
    app.args.apply = False
    p, folder = _saved(app, ["Fred Meyer", "100 Example Rd"])
    del app.progress.data[p.key]["store_info"]
    del app.progress.data[p.key]["store_read"]
    app.discovery.data[p.key]["store_info"] = None
    before = (dict(app.progress.get(p.key)), dict(app.discovery.get(p.key)))
    app.cmd_rename()
    assert (app.progress.get(p.key), app.discovery.get(p.key)) == before


# -- readings of the page -------------------------------------------------------------

def test_a_heading_pypdf_splits_still_ends_the_header():
    lines = HEADER + ["100 Example Rd", "RE WARDS", "Order Summar y", "Item Details",
                      "Kroger Tortilla Chips, 13 oz", "$2.49", "Payment Details",
                      "Alcoholic beverages fulfilled from:", "Northside Grocers"]
    assert site.banner_from_lines(lines) == ""


def test_a_labels_value_on_its_own_line_is_not_the_store():
    lines = ["Order Type:", "In Store", "Order Date:", "Sep. 20, 2026",
             "Northside Grocers", "100 Example Rd"] + BODY
    assert site.banner_from_lines(lines) == "Northside Grocers"
    lines = ["Order Type:", "In Store", "Order Date: Sep. 20, 2026"] + BODY
    assert site.banner_from_lines(lines) == ""


def test_a_name_spaced_out_letter_by_letter_is_not_taken():
    lines = HEADER + ["N o r t h s i d e  G r o c e r s", "100 Example Rd"] + BODY
    assert site.banner_from_lines(lines) == ""
    # a banner this app knows is still read however it is spaced
    lines = HEADER + ["M e t r o  M a r k e t", "100 Example Rd"] + BODY
    assert site.banner_from_lines(lines) == "Metro Market"


def test_payment_lines_are_not_items_even_without_their_heading():
    lines = ["Item Details", "1 Items", "Kroger Tortilla Chips, 13 oz", "$2.49", "1 x $2.49 each",
             "TERMINAL ID 101", "AMEX 1234", "$2.49", "VISA 9876", "$1.00", "CHANGE", "$0.00"]
    assert [i.name for i in site.items_from_lines(lines)] == ["Kroger Tortilla Chips, 13 oz"]
    lines = ["Item Details", "Bottle Deposit", "$0.10", "Bag Fee", "$0.10",
             "Balance Bar Chocolate, 1.76 oz", "$1.25", "Payment Details"]
    assert [i.name for i in site.items_from_lines(lines)] == ["Balance Bar Chocolate, 1.76 oz"]


def test_a_page_without_the_header_costs_no_wait():
    """It waited five seconds a receipt for a header that is not there."""
    waited = []

    class _Loc:
        def count(self):
            return 0

        @property
        def first(self):
            waited.append(True)
            raise TimeoutError("waited five seconds")

    class _Page:
        def locator(self, sel):
            return _Loc()
    assert site.read_banner(_Page()) == ""
    assert waited == [], "a locator that matches nothing was waited on"
