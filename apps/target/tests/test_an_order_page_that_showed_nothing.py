"""An order page that showed neither a receipt nor an invoice is asked for
again (#70).

When no Print receipts control was found, the order was recorded No Receipt
Available, which is final, whether the page showed an invoice in its place
or nothing at all. A page that had not drawn yet shows nothing at all, so
its order was never asked for again, the failure a tester met on Kroger.
Now such an order is a failure the next run asks for again, and only once
three separate days have found nothing is it set aside. An order that shows
only an invoice, with invoices turned off, has no receipt to print and is
recorded as before.

The page is drawn in a real browser. Every number and name is invented.
"""
import csv
import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts
from paperpull_core import receipt_pdf
from paperpull_core.models import ONLINE, Item, Purchase, State
from paperpull_core.testkit import text_pdf

APP_DIR = Path(__file__).resolve().parents[1]

NOTHING = """<main><h1>Order details #102000222</h1><p>Placed Sep 1, 2026</p>
<section><h2>Receipts &amp; invoices</h2></section></main>"""

INVOICE_ONLY = """<main><h1>Order details #102000222</h1><p>Placed Sep 1, 2026</p>
<section><h2>Receipts &amp; invoices</h2><button>View detailed invoices</button></section></main>"""

RUNS = itertools.count(1)


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    pg = browser.new_page()
    yield pg
    browser.close()
    driver.stop()


def a_run(tmp_path, include_invoices=True):
    """The app as one run of it, over the same output folder each time."""
    cfg = json.loads((APP_DIR / "config.example.json").read_text(encoding="utf-8"))
    cfg.update({"owner": "Tester", "output_dir": str(tmp_path / "out"),
                "include_invoices": include_invoices,
                "delay_min_seconds": 0, "delay_max_seconds": 0})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    app = target_receipts.App(target_receipts.build_parser().parse_args(["--config", str(path)]))
    app.stats["started"] = "2031-04-%02dT12:00:00" % next(RUNS)       # a day each
    return app


def purchase():
    return Purchase(purchase_type=ONLINE, purchase_date="2026-09-01", order_number="102000222",
                    total="$12.34", status="Delivered", store_info="Target",
                    details_url="https://www.target.com/orders/102000222",
                    items=[Item(name="Invented thing", quantity="1", line_total="$12.34")])


def rows(app):
    found = 0
    for f in (app.paths.receipt_index_csv, app.paths.order_history_csv):
        if f.exists():
            with open(f, encoding="utf-8-sig", newline="") as fh:
                found += sum(1 for r in csv.DictReader(fh)
                             if r.get("Order or Receipt Number") == "102000222")
    return found


def said(capsys):
    return " ".join(capsys.readouterr().out.split())


def test_a_page_that_showed_nothing_is_asked_for_again(page, tmp_path, capsys):
    page.set_content(NOTHING)
    p = purchase()

    for n in (1, 2):
        app = a_run(tmp_path)
        assert app._handle_no_receipt(page, p) is False
        out = said(capsys)
        assert "Neither a receipt nor an invoice showed, on %d of 3 separate days. " \
               "It is tried again next run." % n in out, out
        rec = app.progress.get(p.key)
        assert rec["state"] == State.FAILED.value, rec
        assert rows(app) == 0, "nothing is written down for an order not saved"
        assert not a_run(tmp_path)._already_done(p), "the next run asks for it again"

    app = a_run(tmp_path)
    app._handle_no_receipt(page, p)
    out = said(capsys)
    assert "on 3 of 3 separate days. It is set aside for review" in out, out
    assert app.progress.get(p.key)["state"] == State.NO_RECEIPT_AVAILABLE.value
    assert rows(app) == 2, "written down once, a row in each CSV"
    assert a_run(tmp_path)._already_done(p), "set aside on the third separate day"


def test_one_run_that_asks_twice_counts_once(page, tmp_path, capsys):
    page.set_content(NOTHING)
    p = purchase()
    app = a_run(tmp_path)
    app._handle_no_receipt(page, p)
    app._handle_no_receipt(page, p)
    assert "on 1 of 3 separate days" in said(capsys)
    assert app.progress.get(p.key)["not_shown_days"] == [app.stats["started"][:10]]


def test_an_order_with_only_an_invoice_has_no_receipt_as_before(page, tmp_path, capsys):
    page.set_content(INVOICE_ONLY)
    p = purchase()
    app = a_run(tmp_path, include_invoices=False)
    assert app._handle_no_receipt(page, p) is False
    assert app.progress.get(p.key)["state"] == State.NO_RECEIPT_AVAILABLE.value
    assert rows(app) == 2
    assert a_run(tmp_path, include_invoices=False)._already_done(p)
    assert "No printable receipt available - marked for manual review." in said(capsys)


def test_a_short_invoice_walk_starts_the_days_again(page, tmp_path, capsys):
    """The page showed nothing on two days. On the third it showed the
    order's invoices and one of its two was saved before the other failed,
    which leaves the record without downloaded_ok. On the fourth it showed
    nothing again. That is one day of nothing since the page showed, so the
    order is asked for again with its second invoice still missing, not set
    aside."""
    page.set_content(NOTHING)
    p = purchase()
    for _ in range(2):
        a_run(tmp_path)._handle_no_receipt(page, p)

    app = a_run(tmp_path)
    text = "Invoice 1 of 2 Invoice number: 10000000000000051 Invented thing Order 102000222"
    staged = app.paths.invoices / "staged.pdf"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(text_pdf([text]))
    walk = {"tokens": receipt_pdf.expected_tokens_for(p), "held": [], "missed": [],
            "count": 2, "list_page": None, "saved": []}
    app._place_invoice(staged, p, (1, 2), (1, 2), "10000000000000051",
                       receipt_pdf.validate_pdf(staged, 2000, walk["tokens"]), text, walk)
    assert app._file_invoices(p, walk) is False
    rec = app.progress.get(p.key)
    assert rec["downloaded_ok"] is False and len(rec["invoices"]) == 1, rec
    assert not rec.get("not_shown_days"), rec
    capsys.readouterr()

    app = a_run(tmp_path)
    app._handle_no_receipt(page, p)
    out = said(capsys)
    assert "on 1 of 3 separate days. It is tried again next run." in out, out
    rec = app.progress.get(p.key)
    assert rec["state"] == State.FAILED.value, rec
    assert len(rec["invoices"]) == 1, "the invoice saved stays on the record"
    assert not a_run(tmp_path)._already_done(p), "the missing invoice is asked for again"
