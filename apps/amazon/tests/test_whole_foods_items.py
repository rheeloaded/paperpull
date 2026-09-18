"""Whole Foods and Amazon Fresh orders print each item as a title line
followed by a line that is only its price, with no "Sold by" and no
quantity, and an item bought twice is listed twice. Before this layout was
known the parser fell back to product names alone, so every Whole Foods
line in the order history had a name and no price."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amazon_site as site
import amazon_receipts
from paperpull_core import receipt_pdf
from paperpull_core.models import Item

WHOLE_FOODS = """Order Summary
Order placed July 12, 2026
Amazon.com order number: 113-0000000-0000000
PICKUP AT
No current charges
Payment method Order Summary
Item(s) Subtotal: $61.95
Shipping & Handling: $0.00
Total before tax: $61.95
Estimated tax to be
collected:
$0.00
Grand Total: $61.95
Purchased at Whole Foods Market
PRODUCE Organic Green Onion
$1.99
Whole Foods Market Sea Scallops 10/20 Count, 12 OZ
$24.49
Banana
$0.93
2
Whole Foods Market Sea Scallops 10/20 Count, 12 OZ
$24.49
Organic Honeycrisp Apple
$10.05
Back to top
Conditions of Use Privacy Notice
"""


def test_title_then_price_pairs_become_items_and_repeats_become_a_quantity():
    items = site._parse_items_from_summary_text(WHOLE_FOODS)
    by = {i.name: i for i in items}
    assert list(by) == ["PRODUCE Organic Green Onion", "Whole Foods Market Sea Scallops 10/20 Count, 12 OZ",
                        "Banana", "Organic Honeycrisp Apple"]
    scallops = by["Whole Foods Market Sea Scallops 10/20 Count, 12 OZ"]
    assert (scallops.quantity, scallops.unit_price, scallops.line_total) == ("2", "$24.49", "$48.98")
    assert by["Banana"].unit_price == "$0.93"          # short names are real items here
    total = sum(site.money_value(i.line_total) for i in items)
    assert round(total, 2) == 61.95 == site.parse_subtotal(WHOLE_FOODS)


def test_the_page_number_between_a_title_and_its_price_is_not_an_item():
    names = [i.name for i in site._parse_items_from_summary_text(WHOLE_FOODS)]
    assert "2" not in names and "Back to top" not in names


def test_summary_lines_are_never_items():
    names = [i.name for i in site._parse_items_from_summary_text(WHOLE_FOODS)]
    assert not any("Subtotal" in n or "Grand Total" in n or "collected" in n for n in names)


def test_the_sold_by_layout_still_wins_when_present():
    text = """Some Product Title That Is Long Enough
Sold by: Amazon.com
Qty: 2
$30.99
Another Line
$5.00
"""
    items = site._parse_items_from_summary_text(text)
    assert [(i.name, i.quantity, i.unit_price) for i in items] == \
        [("Some Product Title That Is Long Enough", "2", "$30.99")]


# -- the offline backfill ------------------------------------------------------

def _app(tmp_path, monkeypatch, pdf_text_by_name, index_rows, progress):
    monkeypatch.setattr(receipt_pdf, "pdf_text", lambda p: pdf_text_by_name.get(Path(p).name, ""))
    app = amazon_receipts.App.__new__(amazon_receipts.App)
    app.args = SimpleNamespace(order_number=None)
    app.stats = {}
    app.index_csv = SimpleNamespace(read_all=lambda: index_rows)
    written = {}
    app.order_csv = SimpleNamespace(read_all=lambda: list(history), rewrite=lambda rows: written.setdefault("rows", rows))
    app.progress = SimpleNamespace(data=progress, update=lambda k, rec: progress.__setitem__(k, rec))
    history = []
    for key, rec in progress.items():
        for it in rec["items"]:
            history.append({"Purchase Type": rec["purchase_type"], "Order or Receipt Number": rec["order_number"],
                            "Item Name": it["name"], "Quantity": it.get("quantity", ""),
                            "Unit Price": it.get("unit_price", ""), "Line Item Total": it.get("line_total", ""),
                            "Order Total": rec["total"], "PDF Filename": rec["pdf_filename"], "Notes": ""})
    return app, written


def _record(order, pdf, items, total="$61.95"):
    return {"purchase_type": "Online", "order_number": order, "purchase_date": "2026-07-12",
            "total": total, "pdf_filename": pdf, "items": items, "notes": ""}


def test_reparse_prices_the_unpriced_order_and_rewrites_only_its_rows(tmp_path, monkeypatch):
    pdf = tmp_path / "wf.pdf"; pdf.write_bytes(b"%PDF-1.4 fake")
    other = tmp_path / "other.pdf"; other.write_bytes(b"%PDF-1.4 fake")
    progress = {
        "Online:113-1": _record("113-1", "wf.pdf", [{"name": "Banana"}, {"name": "Organic Honeycrisp Apple"}]),
        "Online:113-2": _record("113-2", "other.pdf", [{"name": "Kettle", "quantity": "1",
                                                        "unit_price": "$40.00", "line_total": "$40.00"}], "$40.00"),
    }
    index = [{"Purchase Type": "Online", "Order or Receipt Number": "113-1", "PDF Full Path": str(pdf), "PDF Filename": "wf.pdf"},
             {"Purchase Type": "Online", "Order or Receipt Number": "113-2", "PDF Full Path": str(other), "PDF Filename": "other.pdf"}]
    app, written = _app(tmp_path, monkeypatch, {"wf.pdf": WHOLE_FOODS, "other.pdf": "Kettle\nSold by: X\n$40.00"}, index, progress)
    app.cmd_reparse_items()
    items = progress["Online:113-1"]["items"]
    assert [(i["name"], i["quantity"], i["unit_price"]) for i in items][1] == \
        ("Whole Foods Market Sea Scallops 10/20 Count, 12 OZ", "2", "$24.49")
    assert progress["Online:113-2"]["items"][0]["name"] == "Kettle"   # already priced, untouched
    rows = written["rows"]
    assert [r["Item Name"] for r in rows if r["Order or Receipt Number"] == "113-2"] == ["Kettle"]
    mine = [r for r in rows if r["Order or Receipt Number"] == "113-1"]
    assert [r["Unit Price"] for r in mine] == ["$1.99", "$24.49", "$0.93", "$10.05"]
    assert all(r["Order Total"] == "$61.95" and r["PDF Filename"] == "wf.pdf" for r in mine)
    assert all(r["Notes"] == "" for r in mine)        # the parse reconciled exactly


def test_a_parse_that_does_not_add_up_is_refused_or_flagged(tmp_path, monkeypatch):
    pdf = tmp_path / "wf.pdf"; pdf.write_bytes(b"%PDF-1.4 fake")
    index = [{"Purchase Type": "Online", "Order or Receipt Number": "113-1", "PDF Full Path": str(pdf), "PDF Filename": "wf.pdf"}]
    # Overshoot. The page says the items cost less than the parse found.
    progress = {"Online:113-1": _record("113-1", "wf.pdf", [{"name": "Banana"}])}
    app, written = _app(tmp_path, monkeypatch, {"wf.pdf": WHOLE_FOODS.replace("$61.95", "$50.00")}, index, progress)
    app.cmd_reparse_items()
    assert progress["Online:113-1"]["items"] == [{"name": "Banana"}] and "rows" not in written
    # A small shortfall, a bag fee the summary left out, is kept and noted.
    progress = {"Online:113-1": _record("113-1", "wf.pdf", [{"name": "Banana"}])}
    app, written = _app(tmp_path, monkeypatch, {"wf.pdf": WHOLE_FOODS.replace("$61.95", "$63.00")}, index, progress)
    app.cmd_reparse_items()
    assert len(progress["Online:113-1"]["items"]) == 4
    assert "items add to $61.95, receipt subtotal $63.00" in progress["Online:113-1"]["notes"]
    assert all("receipt subtotal $63.00" in r["Notes"] for r in written["rows"])
    # A large shortfall is not this receipt's item list.
    progress = {"Online:113-1": _record("113-1", "wf.pdf", [{"name": "Banana"}])}
    app, written = _app(tmp_path, monkeypatch, {"wf.pdf": WHOLE_FOODS.replace("$61.95", "$120.00")}, index, progress)
    app.cmd_reparse_items()
    assert progress["Online:113-1"]["items"] == [{"name": "Banana"}]


def test_reparse_touches_no_network_and_needs_no_browser():
    src = Path(amazon_receipts.__file__).read_text(encoding="utf-8")
    body = src.split("def cmd_reparse_items")[1].split("def _replace_history_rows")[0]
    assert "self.page(" not in body and "goto" not in body and "site.fetch" not in body
