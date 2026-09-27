"""Apple's real download path, run end to end without a browser.

0.34.0 shipped four apps that passed the capture a keyword it did not
take, and every document they asked for failed while their tests passed,
because none of them ran the loop that makes the call. This runs Apple's
own process_purchases(), through process_one(), _save_receipt() and both
captures, with the page and the site layer's browser calls stubbed and the
capture replaced by paperpull_core.testkit, which holds every call to
render() to its real signature. Every order and name is invented.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_receipts as app_mod
import apple_site as site
from paperpull_core import classification, delivery
from paperpull_core.journal import Journal
from paperpull_core.models import Item, Purchase, State
from paperpull_core.testkit import StrictDelivery

RECEIPT_HTML = "<html><body><p>Receipt</p><p>Order ID: %s</p></body></html>"


class _Store:
    """A progress or discovery store that remembers, in memory."""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def update(self, key, record, save=True):
        self.data.setdefault(key, {}).update(record)

    def save(self, backup=False):
        pass


class _Rows:
    def __init__(self):
        self.rows = []

    def append_rows(self, rows):
        self.rows += list(rows)


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"

    def folder_for(self, key, *a):
        folder = self.root / key
        folder.mkdir(parents=True, exist_ok=True)
        return folder


class _Tab:
    url = "https://secure9.store.apple.com/shop/order/print/invoice/100001/INV0000001"

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Page:
    url = "https://reportaproblem.apple.com/"


def _app(tmp_path, monkeypatch, discovery=None, strict=True, invoice_answers=None):
    app = object.__new__(app_mod.App)
    app.args = None
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000,
                  "refuse_wrong_documents": strict, "owner": "Dana Example"}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates_processed=[])
    app.progress = _Store()
    app.discovery = _Store(discovery)
    app.index_csv, app.order_csv = _Rows(), _Rows()
    app.rules = classification.load_rules(Path(app_mod.__file__).parent / "category_rules.json")
    app._journal = Journal()
    app._opened, app._left_open, app._stopped_sides = [], set(), set()
    app._cdp_mode = True
    failures, tabs, asked = [], [], []
    app.page = lambda: _Page()
    app.browser = lambda: "the store context"
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    app.write_failure = lambda *a, **kw: failures.append(a)

    answers = dict(invoice_answers or {})

    def fetch_invoice(page, weborder, dsid):
        asked.append((weborder, dsid))
        return answers.get(weborder) or {"kind": site.ANSWERED, "status": 200,
                                         "html": RECEIPT_HTML % weborder}

    def open_invoice(context, url):
        assert context == "the store context" and site.is_invoice_url(url)
        tabs.append(_Tab())
        return tabs[-1]

    monkeypatch.setattr(site, "fetch_invoice", fetch_invoice)
    monkeypatch.setattr(site, "open_invoice", open_invoice)
    monkeypatch.setattr(site, "looks_signed_out", lambda page: False)
    monkeypatch.setattr(site, "wait_for_invoice", lambda page, number, timeout_ms=30000: True)
    monkeypatch.setattr(site, "hide_print_controls", lambda page: 1)
    return app, failures, tabs, asked


def app_store(weborder, dsid, name="Premier", detail="Apple One",
              media="Apple One Subscription", date="2026-05-14"):
    purchase = Purchase(purchase_type="App Store", purchase_date=date, order_number=weborder,
                        total="$21.43", details_url=site.REPORT_URL, receipt_url=site.REPORT_URL,
                        items=[Item(name="%s (%s)" % (name, detail), line_total="$21.43")])
    record = purchase.to_dict()
    record.update(dsid=dsid, purchaser="Dana Example", lines=[
        {"name": name, "detail": detail, "media_type": media, "line_item_type": "",
         "amount_paid": "$21.43", "unit_price": "$21.43", "quantity": 1, "free": False}])
    return purchase, record


def apple_store(number, product, status="Delivered", invoiced=True, date="2026-04-28"):
    url = "https://secure9.store.apple.com/shop/order/print/invoice/100001/INV%s" % number[-7:]
    purchase = Purchase(purchase_type="Apple Store", purchase_date=date, order_number=number,
                        total="$655.21", status=status, receipt_url=url if invoiced else "",
                        details_url="https://secure9.store.apple.com/shop/order/detail/100001/" + number,
                        store_info="Apple Store",
                        items=[Item(name=product, line_total="$612.34", status=status)])
    return purchase, purchase.to_dict()


def _run(tmp_path, monkeypatch, rows, **kw):
    discovery = {p.key: rec for p, rec in rows}
    app, failures, tabs, asked = _app(tmp_path, monkeypatch, discovery=discovery, **kw)
    spy = StrictDelivery().install(monkeypatch)
    app.process_purchases([Purchase.from_dict(rec) for _p, rec in rows])
    return app, spy, failures, tabs, asked


def test_both_stores_reach_the_capture_with_arguments_it_accepts(tmp_path, monkeypatch):
    rows = [app_store("MLF0TEST01", "10000001"),
            app_store("MLF0TEST03", "10000002", name="Blockville | 400 Bricks", detail="", media=""),
            apple_store("W0000000001", "13-inch MacBook Air M4 16GB - Sky Blue")]
    app, spy, failures, tabs, asked = _run(tmp_path, monkeypatch, rows)
    assert [c.name for c in spy.calls] == ["render"] * 3
    assert app.stats["failed"] == 0 and not failures
    assert app.stats["receipts_downloaded"] == 3
    assert len(app.stats["new_files"]) == 3
    for call, number in zip(spy.calls, ("MLF0TEST01", "MLF0TEST03", "W0000000001")):
        assert call.arguments["expect"].number == number
        assert call.arguments["strict"] is True
    # The child's receipt is asked for with the child's dsid.
    assert asked == [("MLF0TEST01", "10000001"), ("MLF0TEST03", "10000002")]
    # The invoice tab is closed once it is printed.
    assert len(tabs) == 1 and tabs[0].closed


def test_each_store_files_into_its_own_folder_under_what_was_bought(tmp_path, monkeypatch):
    rows = [app_store("MLF0TEST01", "10000001"),
            apple_store("W0000000001", "13-inch MacBook Air M4 16GB - Sky Blue")]
    app, _spy, _f, _t, _a = _run(tmp_path, monkeypatch, rows)
    names = sorted(Path(p).relative_to(tmp_path).as_posix() for p in app.stats["new_files"])
    assert names == ["App Store/2026-05-14 Apple Apple One Receipt.pdf",
                     "Apple Store/2026-04-28 Apple MacBook Air Receipt.pdf"]
    done = app.progress.get("App Store:MLF0TEST01")
    assert done["state"] == State.COMPLETED.value and done["downloaded_ok"] is True
    assert done["purchaser"] == "Dana Example" and done["dsid"] == "10000001"


def test_a_canceled_order_is_recorded_with_no_receipt(tmp_path, monkeypatch):
    rows = [apple_store("W0000000003", "Mac mini M4 16GB", status="Canceled", invoiced=False)]
    app, spy, failures, tabs, _a = _run(tmp_path, monkeypatch, rows)
    assert spy.calls == [] and tabs == [] and not failures
    assert app.stats["canceled"] == 1
    assert app.progress.get("Apple Store:W0000000003")["state"] == State.CANCELED.value
    assert [r["Receipt Status"] for r in app.index_csv.rows] == ["Canceled"]


def test_an_order_not_invoiced_yet_is_looked_at_again_next_run(tmp_path, monkeypatch):
    rows = [apple_store("W0000000004", "Apple Pencil (USB-C)", status="Processing", invoiced=False)]
    app, spy, failures, _t, _a = _run(tmp_path, monkeypatch, rows)
    assert spy.calls == [] and not failures
    assert app.stats["not_invoiced"] == 1
    assert app.progress.get("Apple Store:W0000000004")["state"] == State.DISCOVERED.value
    assert app.index_csv.rows == [], "nothing is written down for a receipt that is coming"


def test_nothing_rendering_is_a_recorded_failure_not_a_crash(tmp_path, monkeypatch):
    discovery = dict([(p.key, rec) for p, rec in [app_store("MLF0TEST01", "10000001")]])
    app, failures, _t, _a = _app(tmp_path, monkeypatch, discovery=discovery)
    StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()])
    assert app.stats["failed"] == 1 and failures
    assert failures[0][0] == "save the receipt"
    assert not app.stats["new_files"]


def test_a_wrong_receipt_is_counted_for_review_and_not_saved(tmp_path, monkeypatch):
    discovery = dict([(p.key, rec) for p, rec in [app_store("MLF0TEST01", "10000001")]])
    app, failures, _t, _a = _app(tmp_path, monkeypatch, discovery=discovery)
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()])
    assert app.stats["failed"] == 0
    assert app.stats["wrong_document"] == 1 and failures
    assert not app.stats["new_files"]
    assert [r["Receipt Status"] for r in app.index_csv.rows] == ["Wrong document"]


def test_strict_follows_refuse_wrong_documents(tmp_path, monkeypatch):
    _app_, spy, _f, _t, _a = _run(tmp_path, monkeypatch, [app_store("MLF0TEST01", "10000001")],
                                  strict=False)
    assert spy.calls[0].arguments["strict"] is False


def test_no_receipt_back_is_failed_and_tried_again_next_run(tmp_path, monkeypatch):
    rows = [app_store("MLF0TEST01", "10000001")]
    answers = {"MLF0TEST01": {"kind": site.REFUSED, "status": 404, "html": ""}}
    app, spy, failures, _t, _a = _run(tmp_path, monkeypatch, rows, invoice_answers=answers)
    assert spy.calls == [] and failures[0][0] == "fetch the receipt"
    assert app.progress.get("App Store:MLF0TEST01")["state"] == State.FAILED.value
    assert app.stats["no_receipt"] == 1


def test_a_store_sign_in_that_arrives_late_is_a_sign_in_not_a_missing_receipt(
        tmp_path, monkeypatch, capsys):
    """The invoice address loads and then the store sends it to its sign-in
    page. The tab is left there for the person, and the order is asked for
    again next run."""
    rows = [apple_store("W0000000001", "13-inch MacBook Air M4 16GB - Sky Blue")]
    discovery = {p.key: rec for p, rec in rows}
    app, failures, tabs, _a = _app(tmp_path, monkeypatch, discovery=discovery)
    looks = iter([False, True])
    monkeypatch.setattr(site, "looks_signed_out", lambda page: next(looks))
    monkeypatch.setattr(site, "wait_for_invoice", lambda page, number, timeout_ms=30000: False)
    spy = StrictDelivery().install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()])
    assert spy.calls == [] and not failures
    assert app._stopped_sides == {"Apple Store"}
    assert not tabs[0].closed and id(tabs[0]) in app._left_open
    assert app.progress.get("Apple Store:W0000000001")["state"] == State.DISCOVERED.value
    assert "The Apple Store asked you to sign in" in capsys.readouterr().out


def test_a_sign_in_stops_its_own_store_and_the_other_carries_on(tmp_path, monkeypatch, capsys):
    """Report a Problem asking for a sign-in stops the App Store side for the
    rest of the run and leaves its purchase to be asked for again. The
    Apple Store side has its own sign-in and is still read."""
    rows = [app_store("MLF0TEST01", "10000001"), app_store("MLF0TEST02", "10000001"),
            apple_store("W0000000001", "13-inch MacBook Air M4 16GB - Sky Blue")]
    answers = {"MLF0TEST01": {"kind": site.SIGNED_OUT, "status": 401, "html": ""}}
    app, spy, failures, _t, asked = _run(tmp_path, monkeypatch, rows, invoice_answers=answers)
    assert asked == [("MLF0TEST01", "10000001")], "asked once, and never in a loop"
    assert app._stopped_sides == {"App Store"}
    assert app.progress.get("App Store:MLF0TEST01")["state"] == State.DISCOVERED.value
    assert [c.arguments["expect"].number for c in spy.calls] == ["W0000000001"]
    assert "Report a Problem asked you to sign in again" in capsys.readouterr().out
    try:
        app._stop_if_signed_out()
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("a run that stopped for a sign-in must not read as finished")


def test_a_store_that_asked_for_a_sign_in_is_skipped_without_pausing(tmp_path, monkeypatch):
    """The owner's first full run spent ten minutes pausing between purchases
    it only skipped, after Report a Problem asked for a sign-in. A skip asks
    nothing of Apple, so it is not paced. The purchase that met the sign-in
    and the store's order, which is still read, each get their pause."""
    rows = [app_store("MLF0TEST01", "10000001"), app_store("MLF0TEST02", "10000001"),
            app_store("MLF0TEST03", "10000001"),
            apple_store("W0000000001", "13-inch MacBook Air M4 16GB - Sky Blue")]
    answers = {"MLF0TEST01": {"kind": site.SIGNED_OUT, "status": 401, "html": ""}}
    discovery = {p.key: rec for p, rec in rows}
    app, _failures, _tabs, asked = _app(tmp_path, monkeypatch, discovery=discovery,
                                        invoice_answers=answers)
    StrictDelivery().install(monkeypatch)
    paused = []
    app._delay = lambda *a, **kw: paused.append(1)
    app.process_purchases([Purchase.from_dict(rec) for _p, rec in rows])
    assert asked == [("MLF0TEST01", "10000001")]
    assert len(paused) == 2, paused
