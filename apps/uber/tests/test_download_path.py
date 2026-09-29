"""Uber's real download path, run end to end without a browser.

0.34.0 shipped four apps that passed the capture a keyword it did not
take, and every document they asked for failed while their tests passed,
because none of them ran the loop that makes the call. This runs Uber's
own process_purchases(), through process_one(), _save_receipt() and the
capture, with the site layer's browser calls stubbed and delivery replaced
by paperpull_core.testkit, which holds every call to place() to its real
signature. Every trip, order, store and amount is invented.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import uber_receipts as app_mod
import uber_site as site
from paperpull_core import classification, delivery
from paperpull_core.journal import Journal
from paperpull_core.models import Item, Purchase, State
from paperpull_core.testkit import StrictDelivery, sample_pdf

TRIP_A = "0a1b2c3d-1111-4222-8333-444455556666"
TRIP_B = "0a1b2c3d-7777-4888-9999-aaaabbbbcccc"
ORDER_NEW = "5e6f7a8b-1234-4567-89ab-cdef01234567"
ORDER_OLD = "5e6f7a8b-2345-4678-9abc-def012345678"
ORDER_NEAR = "5e6f7a8b-3456-4789-abcd-ef0123456789"
ORDER_FAR = "5e6f7a8b-4567-489a-bcde-f01234567890"
RECEIPT_ID = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
# A real PDF, since what is placed is validated like any download.
PDF = sample_pdf()


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
    def __init__(self, url):
        self.url = url


RIDES_TAB = _Tab("https://riders.uber.com/trips")
EATS_TAB = _Tab("https://www.ubereats.com/orders")


def ride(uuid=TRIP_A, where="Example Station", date="2026-06-15", total="$18.64"):
    purchase = Purchase(purchase_type="Rides", purchase_date=date, order_number=uuid,
                        total=total, status="Completed",
                        details_url="https://riders.uber.com/trips/" + uuid,
                        receipt_url="https://riders.uber.com/trips/" + uuid,
                        items=[Item(name="UberX, 3.1 miles, 12 minutes", line_total=total)])
    record = purchase.to_dict()
    record.update(summary_hint="Ride to %s" % where, vehicle="UberX")
    return purchase, record


def eats(uuid=ORDER_NEW, store="Example Deli", date="2026-04-18", total="$27.35"):
    purchase = Purchase(purchase_type="Uber Eats", purchase_date=date, order_number=uuid,
                        total=total, status="Completed", store_info=store,
                        details_url=site.EATS_ORDERS_URL, receipt_url=site.eats_receipt_url(uuid),
                        items=[Item(name="Turkey Club", quantity="1", unit_price="$12.75",
                                    line_total="$12.75")])
    record = purchase.to_dict()
    record.update(summary_hint="Eats %s" % store)
    return purchase, record


def answered(stamp, receipt_id="", pdf=True):
    return {"kind": site.ANSWERED, "status": 200, "stamp": stamp, "pdf": pdf,
            "receipt_id": receipt_id, "count": 1}


def _app(tmp_path, monkeypatch, discovery=None, strict=True, receipts=None, pdfs=None):
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
    app._requests = None
    app._opened, app._left_open, app._stopped_sides = [], set(), set()
    app._cdp_mode = True
    app._work_page, app._eats_page = RIDES_TAB, EATS_TAB
    failures, asked, fetched = [], [], []
    app.page = lambda: RIDES_TAB
    app.eats_page = lambda: EATS_TAB
    app._delay = lambda *a, **kw: None
    app._already_done = lambda purchase: False
    app.write_failure = lambda *a, **kw: failures.append(a)

    receipts = dict(receipts or {})
    pdfs = dict(pdfs or {})

    def read_ride_receipt(page, uuid):
        assert page is RIDES_TAB, "a ride is asked for from the trips tab"
        asked.append(uuid)
        return receipts.get(uuid) or answered("1781563527104", uuid)

    def read_eats_receipt(page, uuid):
        assert page is EATS_TAB, "an order is asked for from the Uber Eats tab"
        asked.append(uuid)
        return receipts.get(uuid) or answered("2026-04-18T19:22:07.315Z", RECEIPT_ID)

    def fetch_pdf(page, path, side="Rides"):
        fetched.append((page, path, side))
        for uuid, answer in pdfs.items():
            if uuid in path:
                return answer
        return {"kind": site.ANSWERED, "status": 200, "data": PDF}

    monkeypatch.setattr(site, "read_ride_receipt", read_ride_receipt)
    monkeypatch.setattr(site, "read_eats_receipt", read_eats_receipt)
    monkeypatch.setattr(site, "fetch_pdf", fetch_pdf)
    return app, failures, asked, fetched


def _run(tmp_path, monkeypatch, rows, **kw):
    discovery = {p.key: rec for p, rec in rows}
    app, failures, asked, fetched = _app(tmp_path, monkeypatch, discovery=discovery, **kw)
    spy = StrictDelivery().install(monkeypatch)
    app.process_purchases([Purchase.from_dict(rec) for _p, rec in rows])
    return app, spy, failures, asked, fetched


def test_both_kinds_reach_place_with_arguments_it_accepts(tmp_path, monkeypatch):
    rows = [ride(), eats()]
    app, spy, failures, asked, fetched = _run(tmp_path, monkeypatch, rows)
    assert [c.name for c in spy.calls] == ["place"] * 2
    assert app.stats["failed"] == 0 and not failures
    assert app.stats["receipts_downloaded"] == 2 and len(app.stats["new_files"]) == 2
    assert [c.arguments["expect"].number for c in spy.calls] == [TRIP_A, RECEIPT_ID]
    assert all(c.arguments["strict"] is True and c.arguments["data"] == PDF for c in spy.calls)
    assert asked == [TRIP_A, ORDER_NEW], "each receipt is asked for once"
    assert [(p, path, side) for p, path, side in fetched] == [
        (RIDES_TAB, "/trips/%s/receipt?contentType=PDF&timestamp=1781563527104" % TRIP_A, "Rides"),
        (EATS_TAB, "/orders/%s/download-receipt?contentType=PDF&timestamp=2026-04-18T19:22:07.315Z"
         % ORDER_NEW, "Uber Eats")]


def test_each_kind_files_into_its_own_folder_under_the_name_uber_gave_it(tmp_path, monkeypatch):
    app, _spy, _f, _a, _p = _run(tmp_path, monkeypatch, [ride(), eats()])
    names = sorted(Path(p).relative_to(tmp_path).as_posix() for p in app.stats["new_files"])
    assert names == ["Rides/2026-06-15 Uber Ride to Example Station Receipt.pdf",
                     "Uber Eats/2026-04-18 Uber Eats Example Deli Receipt.pdf"]
    done = app.progress.get("Rides:" + TRIP_A)
    assert done["state"] == State.COMPLETED.value and done["downloaded_ok"] is True
    assert done["confidence"] == "High" and done["vehicle"] == "UberX"
    assert [r["Receipt Status"] for r in app.index_csv.rows] == ["Downloaded", "Downloaded"]


def test_a_ride_receipt_that_names_no_id_is_held_to_the_trips_own(tmp_path, monkeypatch):
    """Every ride receipt prints the trip's uuid as its Receipt ID, RECORDED,
    so a receipt answer that did not show it still expects that one."""
    receipts = {TRIP_A: answered("1781563527104", receipt_id="")}
    app, spy, _f, _a, _p = _run(tmp_path, monkeypatch, [ride()], receipts=receipts)
    assert spy.calls[0].arguments["expect"].number == TRIP_A
    assert spy.calls[0].arguments["rivals"] == ()


def test_an_older_eats_receipt_is_held_to_its_own_date_and_total(tmp_path, monkeypatch):
    """Receipts before December 2025 print no Receipt ID, so the date and
    total are asked for. Neighbors are never counted, since a review of
    0.40.0 found that refusing and destroying a correct receipt."""
    rows = [eats(ORDER_OLD, date="2025-10-30", total="$22.91"),
            eats(ORDER_NEAR, store="Example Noodles", date="2025-11-01", total="$18.40"),
            eats(ORDER_FAR, store="Example Pizza", date="2025-09-20", total="$31.00"),
            ride(TRIP_B, date="2025-10-30", total="$22.91")]
    receipts = {ORDER_OLD: answered("2025-10-30T17:41:26.208Z", receipt_id="")}
    discovery = {p.key: rec for p, rec in rows}
    app, _failures, _asked, _fetched = _app(tmp_path, monkeypatch, discovery=discovery,
                                            receipts=receipts)
    spy = StrictDelivery().install(monkeypatch)
    app.process_purchases([Purchase.from_dict(rows[0][1])])
    expect = spy.calls[0].arguments["expect"]
    assert not expect.number and expect.date == "2025-10-30" and expect.total == "$22.91"
    assert spy.calls[0].arguments["rivals"] == ()


def test_no_receipt_offered_is_failed_and_tried_again_next_run(tmp_path, monkeypatch):
    receipts = {TRIP_A: answered("", pdf=False)}
    app, spy, failures, _a, fetched = _run(tmp_path, monkeypatch, [ride()], receipts=receipts)
    assert spy.calls == [] and fetched == []
    assert failures[0][0] == "fetch the receipt"
    assert app.progress.get("Rides:" + TRIP_A)["state"] == State.FAILED.value
    assert app.stats["no_receipt"] == 1


def test_a_pdf_that_does_not_come_is_failed_not_saved(tmp_path, monkeypatch):
    pdfs = {TRIP_A: {"kind": site.REFUSED, "status": 404, "data": b""}}
    app, spy, failures, _a, _p = _run(tmp_path, monkeypatch, [ride()], pdfs=pdfs)
    assert spy.calls == [] and failures[0][0] == "fetch the receipt"
    assert not app.stats["new_files"]


def test_a_sign_in_stops_its_own_side_and_the_other_carries_on(tmp_path, monkeypatch, capsys):
    rows = [ride(TRIP_A), ride(TRIP_B), eats()]
    receipts = {TRIP_A: {"kind": site.SIGNED_OUT, "status": 0, "stamp": "", "pdf": False,
                         "receipt_id": "", "count": 0}}
    app, spy, failures, asked, _p = _run(tmp_path, monkeypatch, rows, receipts=receipts)
    assert asked == [TRIP_A, ORDER_NEW], "the second ride is not asked for"
    assert app._stopped_sides == {"Rides"}
    assert app.progress.get("Rides:" + TRIP_A)["state"] == State.DISCOVERED.value
    assert [c.arguments["expect"].number for c in spy.calls] == [RECEIPT_ID]
    assert "Uber asked you to sign in again for your trips" in capsys.readouterr().out
    try:
        app._stop_if_signed_out()
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("a run that stopped for a sign-in must not read as finished")


def test_a_sign_in_that_arrives_at_the_pdf_is_a_sign_in(tmp_path, monkeypatch, capsys):
    pdfs = {ORDER_NEW: {"kind": site.SIGNED_OUT, "status": 0, "data": b""}}
    app, spy, failures, _a, _p = _run(tmp_path, monkeypatch, [eats()], pdfs=pdfs)
    assert spy.calls == [] and not failures
    assert app._stopped_sides == {"Uber Eats"} and id(EATS_TAB) in app._left_open
    assert app.progress.get("Uber Eats:" + ORDER_NEW)["state"] == State.DISCOVERED.value
    assert "Uber Eats asked you to sign in" in capsys.readouterr().out


def test_a_side_that_asked_for_a_sign_in_is_skipped_without_pausing(tmp_path, monkeypatch):
    rows = [ride(TRIP_A), ride(TRIP_B), eats()]
    receipts = {TRIP_A: {"kind": site.SIGNED_OUT, "status": 401, "stamp": "", "pdf": False,
                         "receipt_id": "", "count": 0}}
    discovery = {p.key: rec for p, rec in rows}
    app, _f, asked, _p = _app(tmp_path, monkeypatch, discovery=discovery, receipts=receipts)
    StrictDelivery().install(monkeypatch)
    paused = []
    app._delay = lambda *a, **kw: paused.append(1)
    app.process_purchases([Purchase.from_dict(rec) for _p2, rec in rows])
    assert asked == [TRIP_A, ORDER_NEW]
    assert len(paused) == 2, paused


def test_nothing_placed_is_a_recorded_failure_not_a_crash(tmp_path, monkeypatch):
    discovery = dict([(p.key, rec) for p, rec in [ride()]])
    app, failures, _a, _p = _app(tmp_path, monkeypatch, discovery=discovery)
    StrictDelivery(outcome=delivery.NOT_PLACED).install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()])
    assert app.stats["failed"] == 1 and failures[0][0] == "save the receipt"
    assert not app.stats["new_files"]


def test_a_wrong_receipt_is_counted_for_review_and_not_saved(tmp_path, monkeypatch):
    discovery = dict([(p.key, rec) for p, rec in [eats()]])
    app, failures, _a, _p = _app(tmp_path, monkeypatch, discovery=discovery)
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()])
    assert app.stats["failed"] == 0
    assert app.stats["wrong_document"] == 1 and failures
    assert not app.stats["new_files"]
    assert [r["Receipt Status"] for r in app.index_csv.rows] == ["Wrong document"]


def test_strict_follows_refuse_wrong_documents(tmp_path, monkeypatch):
    _app_, spy, _f, _a, _p = _run(tmp_path, monkeypatch, [ride()], strict=False)
    assert spy.calls[0].arguments["strict"] is False


def test_a_dry_run_asks_uber_for_nothing(tmp_path, monkeypatch, capsys):
    discovery = dict([(p.key, rec) for p, rec in [ride(), eats()]])
    app, _f, asked, fetched = _app(tmp_path, monkeypatch, discovery=discovery)
    spy = StrictDelivery().install(monkeypatch)
    app.process_purchases([Purchase.from_dict(r) for r in discovery.values()], dry_run=True)
    assert asked == [] and fetched == [] and spy.calls == []
    assert "would save 2026-06-15 Uber Ride to Example Station Receipt.pdf" in capsys.readouterr().out


# -- discovery after a sign-out, and a trip whose details do not answer ------------

ROW = {"uuid": TRIP_A, "title": "Example Station", "description": "$18.64",
       "subtitle": "Jun 15 \u2022 1:55 PM", "_window": ["", ""]}


def _discovering(tmp_path, monkeypatch, walk, trip_answer):
    app, failures, _asked, _fetched = _app(tmp_path, monkeypatch)
    app._open = lambda side: RIDES_TAB
    app.args = type("Args", (), {"start_date": None, "year": None})()
    app.config["default_start_date"] = ""
    trips = []
    monkeypatch.setattr(site, "walk_rides", lambda page, limit_date="": walk)

    def read_trip(page, uuid):
        trips.append(uuid)
        return trip_answer
    monkeypatch.setattr(site, "read_trip", read_trip)
    return app, failures, trips


def test_no_trip_is_asked_about_once_the_list_said_sign_in(tmp_path, monkeypatch, capsys):
    """A review of 0.40.0 found the trips read before a sign-out asked about
    one by one from a tab on the sign-in page, and recorded from their
    subtitles alone."""
    walk = {"rides": [ROW], "pages": 1, "stop": site.SIGNED_OUT, "status": 0}
    app, failures, trips = _discovering(tmp_path, monkeypatch, walk, None)
    assert app._discover_rides() == 0
    assert trips == [] and app.discovery.data == {}
    assert app._stopped_sides == {"Rides"} and not failures
    assert "Uber asked you to sign in again for your trips" in capsys.readouterr().out


def test_a_trip_whose_details_do_not_answer_is_not_recorded_from_its_subtitle(
        tmp_path, monkeypatch, capsys):
    walk = {"rides": [ROW], "pages": 1, "stop": site.END, "status": 200}
    app, failures, trips = _discovering(tmp_path, monkeypatch, walk,
                                        {"kind": site.FAILED, "status": 0, "trip": {}})
    assert app._discover_rides() == 0
    assert trips == [TRIP_A] and app.discovery.data == {}
    assert failures and failures[0][1] == "a trip's details were not answered"
    assert "did not answer with their details" in capsys.readouterr().out
