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
from paperpull_core.models import ONLINE, Item, Purchase, State

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
    assert a_run(tmp_path)._already_done(p), "set aside after three runs"


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
