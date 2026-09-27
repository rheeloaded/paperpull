"""A gas station receipt is named for what it is, and Diagnose can say why
when it is not (#47).

Driven through the orchestrator with the page and the site layer's page
reads stubbed, because the name is decided in process_one and the survey
in cmd_diagnose, and a test of the site layer alone passed the first fix
while the name still rested on one exact order of text nobody has seen.

Every receipt here is invented.
"""
import contextlib
import io
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import costco_receipts as app_mod
import costco_site as site
from paperpull_core import classification
from paperpull_core.journal import Journal
from paperpull_core.models import IN_STORE, ONLINE, Purchase


class _Store:
    def __init__(self):
        self.data = {}

    def update(self, key, rec=None, **kw):
        self.data.setdefault(key, {}).update(rec or {})

    def append_rows(self, *a, **kw):
        pass

    def get(self, key, *a, **kw):
        return self.data.get(key)


class _Page:
    url = "https://www.costco.com/myaccount/#/app/ordersandpurchases"


# A gas receipt whose tables came out in a way no reader here knows. The
# heading is all there is to go on.
UNREADABLE_GAS = """Close
Gas Station Receipt
SPRINGFIELD #1234
Pump 4 Gallons Price
Regular
Total Sale"""

# The same kind of receipt read the way the member's paste came out.
READABLE_GAS = """Gas Station Receipt
SPRINGFIELD #1234
Pump
Gallons
Price
4
11.204
$3.299
Product
Amount
Regular
$36.96
Total Sale
$36.96"""

WAREHOUSE = """In-Warehouse Receipt
SPRINGFIELD #1234
E 123456 KS PAPER TOWELS 19.99 Y
E 234567 BANANAS 1.99 3
SUBTOTAL 21.98
**** TOTAL 21.98"""


def _app(monkeypatch, receipt):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress, app.discovery = _Store(), _Store()
    app.rules = None
    app._journal = Journal()
    app.page = lambda: _Page()
    app.check_session = lambda page: None
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    monkeypatch.setattr(site, "goto_receipt", lambda page, purchase: None)
    monkeypatch.setattr(site, "receipt_text", lambda page: receipt)
    return app


def _warehouse_visit():
    """What a Warehouse tab row becomes, gas stop or not."""
    return Purchase(purchase_type=IN_STORE, order_number="wh-20260315-3696-SPRINGFIELD",
                    purchase_date="2026-03-15", total="$36.96",
                    store_info="In-Warehouse")


def _run(app, purchase):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        app.process_purchases([purchase], dry_run=True)
    return out.getvalue()


def test_a_gas_receipt_whose_tables_read_nothing_is_still_a_gas_station(monkeypatch):
    """The first fix named it only when the pump's cells came out in one
    exact order, and otherwise it was Mixed Purchases, the name the member
    reported. The receipt's own heading does not depend on that order."""
    purchase = _warehouse_visit()
    said = _run(_app(monkeypatch, UNREADABLE_GAS), purchase)
    assert purchase.items == []
    assert purchase.summary == "Gas Station"
    assert purchase.confidence == classification.HIGH
    assert "Gas Station Receipt" in said


def test_a_readable_gas_receipt_is_a_gas_station_with_its_fuel_line(monkeypatch):
    purchase = _warehouse_visit()
    said = _run(_app(monkeypatch, READABLE_GAS), purchase)
    assert [(i.name, i.quantity, i.unit_price, i.line_total) for i in purchase.items] == [
        ("Regular Fuel", "11.204", "$3.299", "$36.96")]
    assert purchase.summary == "Gas Station"
    assert "1 item(s); summary: Gas Station [High]" in said


def test_a_warehouse_receipt_is_still_named_by_its_items(monkeypatch):
    purchase = _warehouse_visit()
    _run(_app(monkeypatch, WAREHOUSE), purchase)
    expected = classification.classify_items(purchase.items, None)
    assert len(purchase.items) == 2
    assert purchase.summary == expected.summary
    assert purchase.summary != "Gas Station"


def test_an_online_order_never_reads_a_heading_it_does_not_have(monkeypatch):
    """The print view is not a dialog, so there is no dialog text."""
    purchase = Purchase(purchase_type=ONLINE, order_number="1234567890",
                        purchase_date="2026-03-15", total="$36.96",
                        store_info="Online")
    _run(_app(monkeypatch, ""), purchase)
    assert purchase.summary != "Gas Station"


# -- Diagnose ----------------------------------------------------------------

ROW = {"purchaseType": "WAREHOUSE", "href": "", "createdDateTime": "2026-03-15",
       "total": "$36.96", "status": "", "where": "SPRINGFIELD", "index": 0,
       "cardText": "In-Warehouse 03/15/2026 SPRINGFIELD Total $36.96 View Receipt"}

# Private-looking words the safe survey must not carry. All invented.
DIAGNOSED = READABLE_GAS.replace(
    "SPRINGFIELD #1234", "SPRINGFIELD #1234\n4321 Dansk Ct\nPat Morgan\nVISA XXXX1111")


def _diagnose(tmp_path, monkeypatch):
    app = object.__new__(app_mod.App)
    app.stats = defaultdict(int)
    app.args = SimpleNamespace(order_number=None)
    app.config = {"owner": ""}
    app.paths = SimpleNamespace(diagnostics=tmp_path)
    app.page = lambda: _Page()
    app._journal = Journal()
    app._requests = None
    for name, value in (("goto_orders", None), ("looks_signed_out", False),
                        ("detect_security_challenge", None), ("goto_receipt", None)):
        monkeypatch.setattr(site, name, lambda *a, v=value, **kw: v)
    monkeypatch.setattr(site, "survey_history_page", lambda page: {})
    monkeypatch.setattr(site, "fetch_history", lambda page, **kw: {"records": [dict(ROW)]})
    monkeypatch.setattr(site, "survey_receipt_page", lambda page: site.ReceiptSurvey())
    monkeypatch.setattr(site, "receipt_text", lambda page: DIAGNOSED)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        app.cmd_diagnose()
        app.write_survey()
    return out.getvalue()


def test_the_survey_carries_the_receipts_layout_and_nothing_from_it(tmp_path, monkeypatch):
    """The first round asked for a Diagnose file that could not show the
    order of the receipt's cells, which is the one thing a failing round
    needs. The safe survey now carries it, as words from a fixed list."""
    _diagnose(tmp_path, monkeypatch)
    surveys = list(tmp_path.glob("survey-*.json"))
    assert len(surveys) == 1
    raw = surveys[0].read_text(encoding="utf-8")
    receipt = json.loads(raw)["extra"]["receipt"]
    assert receipt["heading"] == "gas station"
    assert receipt["items"] == 1 and receipt["pump_read"] is True
    assert receipt["layout"] == site.receipt_layout(DIAGNOSED)
    assert "pump" in receipt["layout"] and "product" in receipt["layout"]
    for private in ("SPRINGFIELD", "Dansk", "Morgan", "XXXX1111", "11.204", "36.96"):
        assert private not in raw, private


def test_the_detailed_file_is_not_the_one_it_says_to_attach(tmp_path, monkeypatch):
    """It ended by telling the member to attach the detailed file, which
    carries the page's own words, straight after saying it stays here."""
    said = _diagnose(tmp_path, monkeypatch)
    assert "Attach it to the GitHub issue" not in said
    assert "Do not attach this one" in said
    detailed = json.loads((tmp_path / "diagnose-costco.json").read_text(encoding="utf-8"))
    assert detailed["receipt"]["shape"]["heading"] == "gas station"
