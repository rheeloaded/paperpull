"""Records kept from Meijer's earlier orders page are adopted by the purchase
the current page lists for them, and never guessed (review of #236).

A purchase's key is a digest of its row's words, and the current page words
every row differently, so a receipt saved from the earlier page came out
under a new key and was saved a second time beside the first, and a record
of the earlier page never saved failed on every run. A record moves to the
new key only when exactly one record and one purchase of a kind, day,
amount and store fit. Anything else is held when something of it was saved,
and otherwise fetched under the new key with the old records retired.

The real cmd_discover runs, with only the page stood in for. Every date,
store, amount and key is invented.
"""
import hashlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import meijer_receipts as mr
import meijer_site as site
from paperpull_core import classification
from paperpull_core import storage as core_storage
from paperpull_core.models import IN_STORE, ONLINE, Purchase

OLD_ROW = "In-Store: 09/19/2026\n1600 Invented Road\n$31.23  6 items"
OLD_KEY = "In-Store:pdd68c0110267"
NEW_1141 = "In-Store: September 19, 2026, 11:41 am\n1600 Invented Road\n$31.23 2 items"
NEW_0402 = "In-Store: September 19, 2026, 4:02 pm\n1600 Invented Road\n$31.23 2 items"
ELSEWHERE = "In-Store: September 18, 2026, 9:05 am\n77 Example Street\n$12.80 3 items"
OTHER_OLD_ROW = "In-Store: 9/19/2026\n1600 Invented Road\n$31.23  6 items"


# The record fields this change writes, read with a default so the tests
# that guard behavior kept from 453f3ad9 run there too, for the fail-before.
HELD = getattr(mr, "HELD", "held")
HELD_REASON = getattr(mr, "HELD_REASON", "")
ADOPTED_FROM = getattr(mr, "ADOPTED_FROM", "adopted_from")
ROW_PRINTS_TIME = getattr(mr, "ROW_PRINTS_TIME", "row_prints_time")


def card(text):
    return site.RawCard(text=text)


def key_of(text):
    return site.card_to_purchase(card(text)).key


NEW_KEY = key_of(NEW_1141)
TWIN_KEY = key_of(NEW_0402)


@pytest.fixture(autouse=True)
def default_names():
    storage.set_filename_owner("")
    core_storage.set_filename_patterns({})
    yield


def make_app(tmp_path, **args):
    app = object.__new__(mr.App)
    base = dict(start_date=None, end_date=None, year=None, order_number=None,
                max_purchases=0, redownload=False, dry_run=False, yes=True)
    base.update(args)
    app.args = SimpleNamespace(**base)
    app.config = {"min_pdf_bytes": 3000, "max_path_length": 240, "owner": "",
                  "delay_min_seconds": 0, "delay_max_seconds": 0,
                  "default_start_date": None, "pilot_online": 5, "pilot_instore": 5}
    app.paths = storage.Paths(tmp_path)
    app.paths.ensure()
    app.progress = storage.JsonStore(app.paths.progress_json, app.paths.backups)
    app.progress.data, app.progress._loaded = {}, True
    app.discovery = storage.JsonStore(app.paths.discovery_json, app.paths.backups)
    app.discovery.data, app.discovery._loaded = {}, True
    app.order_csv = storage.CsvFile(app.paths.order_history_csv, storage.ORDER_HISTORY_COLUMNS)
    app.index_csv = storage.CsvFile(app.paths.receipt_index_csv, storage.RECEIPT_INDEX_COLUMNS)
    app.rules = classification.load_rules()
    app._list_cut_short = False
    app.stats = {"validation_failures": 0, "manual_review": 0, "new_files": [],
                 "receipts_downloaded": 0, "no_receipt": 0, "failed": 0,
                 "duplicate_filenames": 0, "skipped_completed": 0, "canceled": 0,
                 "dates_processed": [], "online_discovered": 0}
    app.failures = []
    app.write_failure = lambda step, reason, **k: app.failures.append((step, reason))
    return app


def old_record(row=OLD_ROW, **fields):
    rec = site.card_to_purchase(card(row)).to_dict()
    rec["state"] = "Discovered"
    rec.update(fields)
    return rec


def put_saved(app, tmp_path, row=OLD_ROW, name="2026-09-19 Meijer Groceries Receipt.pdf"):
    """A receipt saved from the earlier page, its record in both stores and
    its file on disk, as a run at 453f3ad9 leaves one."""
    folder = app.paths.folder_for(IN_STORE, "Receipt")
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / name
    pdf.write_bytes(b"%PDF-1.4 invented 0919 " + b"x" * 4000)
    rec = old_record(row, state="Completed", downloaded_ok=True, pdf_filename=name,
                     pdf_path=str(pdf), summary="Groceries", notes="invented note",
                     confidence="High")
    key = site.card_to_purchase(card(row)).key
    app.progress.data[key] = dict(rec)
    app.discovery.data[key] = dict(rec)
    return key, pdf


def put_unsaved(app, row=OLD_ROW, progress=None, **fields):
    key = site.card_to_purchase(card(row)).key
    app.discovery.data[key] = old_record(row, **fields)
    if progress is not None:
        app.progress.data[key] = old_record(row, **progress)
    return key


def write_stores(app):
    app.progress.save()
    app.discovery.save()


def discover(app, monkeypatch, rows, read=(IN_STORE, ONLINE), unsettled=(), unread=()):
    """The real discovery over a page that lists these rows."""
    monkeypatch.setattr(mr.App, "page", lambda self: object())
    monkeypatch.setattr(mr.App, "_open_orders", lambda self, page: None)
    monkeypatch.setattr(mr.App, "check_session", lambda self, page: False)

    def both(page, facts=None):
        if facts is not None:
            facts["read"] = list(read)
            facts["unsettled"] = list(unsettled)
            facts["unread"] = list(unread)
        return [card(r) for r in rows]

    monkeypatch.setattr(site, "collect_both_tabs", both)
    monkeypatch.setattr(site, "goto_orders", lambda page, n=1: True)
    monkeypatch.setattr(site, "collect_cards", lambda page, *a, **k: [])
    app._list_cut_short = False
    return app.cmd_discover(quiet=True, finish=False)


def pressed(app, monkeypatch):
    seen = []
    monkeypatch.setattr(mr.App, "process_one",
                        lambda self, page, purchase, dry_run=False: seen.append(purchase.key))
    monkeypatch.setattr(mr.App, "_delay", lambda self, f=1.0: None)
    monkeypatch.setattr(mr.App, "journal", property(lambda self: SimpleNamespace(op=lambda *a, **k: None)))
    return seen


def run_all(app, monkeypatch):
    seen = pressed(app, monkeypatch)
    app.process_purchases(app._select_purchases(None, limit=0))
    return seen


def is_held(app, key):
    return bool((app.discovery.get(key) or {}).get(HELD))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# -- exactly one fits -------------------------------------------------------

def test_the_fixture_keys_are_the_ones_pinned():
    assert key_of(OLD_ROW) == OLD_KEY
    assert NEW_KEY != OLD_KEY and TWIN_KEY not in (NEW_KEY, OLD_KEY)


def test_a_saved_old_record_is_adopted_by_the_one_purchase_that_fits(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    _key, pdf = put_saved(app, tmp_path)
    before = dict(app.progress.data[OLD_KEY])
    discover(app, monkeypatch, [NEW_1141, ELSEWHERE])
    assert OLD_KEY not in app.progress.data and OLD_KEY not in app.discovery.data
    rec = app.progress.data[NEW_KEY]
    assert rec["order_number"] == NEW_KEY.split(":", 1)[1]
    assert rec[ADOPTED_FROM] == OLD_KEY.split(":", 1)[1]
    for field in ("downloaded_ok", "state", "pdf_path", "pdf_filename", "summary", "notes",
                  "confidence", "items", "discovered_at"):
        assert rec[field] == before[field], field
    assert app.discovery.data[NEW_KEY][ADOPTED_FROM] == OLD_KEY.split(":", 1)[1]
    assert app._already_done(Purchase.from_dict(app.discovery.data[NEW_KEY]))
    assert not is_held(app, NEW_KEY)


def test_an_unsaved_old_record_is_adopted_and_selected_under_its_new_key(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_unsaved(app, progress={"state": "Failed", "notes": "invented failure"})
    discover(app, monkeypatch, [NEW_1141, ELSEWHERE])
    assert app.progress.data[NEW_KEY]["notes"] == "invented failure"
    assert app.discovery.data[NEW_KEY][ADOPTED_FROM] == OLD_KEY.split(":", 1)[1]
    keys = [p.key for p in app._select_purchases(IN_STORE, limit=0)]
    assert NEW_KEY in keys and OLD_KEY not in keys
    assert not app._already_done(Purchase.from_dict(app.discovery.data[NEW_KEY]))


def test_a_saved_adopted_record_is_never_pressed_and_its_file_is_untouched(tmp_path, monkeypatch, capsys):
    app = make_app(tmp_path)
    _key, pdf = put_saved(app, tmp_path)
    before = (digest(pdf), pdf.name, pdf.stat().st_mtime_ns)
    files = sorted(p.name for p in pdf.parent.iterdir())
    discover(app, monkeypatch, [NEW_1141, ELSEWHERE])
    seen = run_all(app, monkeypatch)
    assert NEW_KEY not in seen and OLD_KEY not in seen
    assert seen == [key_of(ELSEWHERE)]
    assert "Already completed" in capsys.readouterr().out
    assert (digest(pdf), pdf.name, pdf.stat().st_mtime_ns) == before
    assert sorted(p.name for p in pdf.parent.iterdir()) == files


def test_a_discovery_listing_under_the_new_key_gives_way_to_the_adopted_record(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    listing = site.card_to_purchase(card(NEW_1141)).to_dict()
    listing["state"] = "Discovered"
    app.discovery.data[NEW_KEY] = listing
    discover(app, monkeypatch, [NEW_1141])
    assert app.discovery.data[NEW_KEY]["downloaded_ok"] is True
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True


def test_the_store_matches_with_case_and_spacing_folded(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    folded = "In-Store: September 19, 2026, 11:41 am\n1600  INVENTED road\n$31.23 2 items"
    discover(app, monkeypatch, [folded])
    assert app.progress.data[key_of(folded)]["downloaded_ok"] is True
    assert OLD_KEY not in app.progress.data


def test_an_online_record_is_adopted_by_an_online_purchase(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    old = old_record(OLD_ROW, purchase_type=ONLINE, order_number="pinventedonline",
                     state="Completed", downloaded_ok=True)
    app.progress.data["Online:pinventedonline"] = old
    app.discovery.data["Online:pinventedonline"] = dict(old)
    new_online = "Online: September 19, 2026, 11:41 am\n1600 Invented Road\n$31.23 2 items"
    discover(app, monkeypatch, [new_online])
    assert app.progress.data[key_of(new_online)]["downloaded_ok"] is True
    assert "Online:pinventedonline" not in app.progress.data


# -- two or more old records fit one purchase ------------------------------

def test_two_saved_old_records_fitting_one_purchase_adopt_nothing_and_hold_it(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    first, _ = put_saved(app, tmp_path)
    second, _ = put_saved(app, tmp_path, row=OTHER_OLD_ROW, name="2026-09-19 Meijer Other Receipt.pdf")
    assert first != second
    discover(app, monkeypatch, [NEW_1141, ELSEWHERE])
    assert first in app.progress.data and second in app.progress.data
    assert NEW_KEY not in app.progress.data
    assert is_held(app, NEW_KEY)
    assert run_all(app, monkeypatch) == [key_of(ELSEWHERE)]


def test_one_saved_and_one_unsaved_old_record_hold_the_purchase_and_the_unsaved_one(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    saved, _ = put_saved(app, tmp_path)
    unsaved = put_unsaved(app, row=OTHER_OLD_ROW)
    discover(app, monkeypatch, [NEW_1141])
    assert is_held(app, NEW_KEY) and is_held(app, unsaved) and not is_held(app, saved)
    assert run_all(app, monkeypatch) == []


def test_two_unsaved_old_records_are_retired_and_the_purchase_downloads(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    a = put_unsaved(app, progress={"state": "Failed", "notes": "invented"})
    b = put_unsaved(app, row=OTHER_OLD_ROW)
    discover(app, monkeypatch, [NEW_1141])
    assert a not in app.discovery.data and b not in app.discovery.data
    assert app.progress.data[a]["notes"] == "invented"
    assert not is_held(app, NEW_KEY)
    assert run_all(app, monkeypatch) == [NEW_KEY]


# -- two or more new-page purchases fit one old record ----------------------

def test_twins_fitting_one_saved_old_record_are_both_held(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402, ELSEWHERE])
    assert OLD_KEY in app.progress.data
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    assert run_all(app, monkeypatch) == [key_of(ELSEWHERE)]


@pytest.mark.parametrize("twin_state", [{"state": "Failed"},
                                        {"state": "Completed", "downloaded_ok": True}])
def test_twins_where_one_already_has_a_record_still_count_as_two(tmp_path, monkeypatch, twin_state):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    app.progress.data[TWIN_KEY] = dict(site.card_to_purchase(card(NEW_0402)).to_dict(), **twin_state)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert OLD_KEY in app.progress.data and NEW_KEY not in app.progress.data
    assert is_held(app, NEW_KEY)
    assert app.progress.data[TWIN_KEY]["state"] == twin_state["state"]


def test_twins_fitting_one_unsaved_old_record_download_and_the_old_one_retires(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_unsaved(app)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert OLD_KEY not in app.discovery.data
    assert not is_held(app, NEW_KEY) and not is_held(app, TWIN_KEY)
    assert sorted(run_all(app, monkeypatch)) == sorted([NEW_KEY, TWIN_KEY])


# -- one purchase that has a record, and one old record --------------------

def test_a_purchase_with_a_record_keeps_it_and_an_unsaved_old_one_retires(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_unsaved(app)
    mine = dict(site.card_to_purchase(card(NEW_1141)).to_dict(), state="Failed", notes="its own")
    app.progress.data[NEW_KEY] = dict(mine)
    discover(app, monkeypatch, [NEW_1141])
    assert app.progress.data[NEW_KEY] == mine
    assert OLD_KEY not in app.discovery.data


def test_a_purchase_with_a_record_and_a_saved_old_one_leave_both_as_they_are(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    old = dict(app.progress.data[OLD_KEY])
    mine = dict(site.card_to_purchase(card(NEW_1141)).to_dict(), state="Failed")
    app.progress.data[NEW_KEY] = dict(mine)
    discover(app, monkeypatch, [NEW_1141])
    assert app.progress.data[NEW_KEY] == mine and app.progress.data[OLD_KEY] == old
    assert OLD_KEY in app.discovery.data and not is_held(app, NEW_KEY)


# -- the start date floor ---------------------------------------------------

def test_a_group_before_the_floor_is_left_as_it_is(tmp_path, monkeypatch):
    app = make_app(tmp_path, start_date="2026-09-20")
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141])
    assert OLD_KEY in app.progress.data and NEW_KEY not in app.progress.data
    assert NEW_KEY not in app.discovery.data


# -- each fact differing alone fits nothing ---------------------------------

@pytest.mark.parametrize("row", [
    "Online: September 19, 2026, 11:41 am\n1600 Invented Road\n$31.23 2 items",   # kind
    "In-Store: September 20, 2026, 11:41 am\n1600 Invented Road\n$31.23 2 items",  # date
    "In-Store: September 19, 2026, 11:41 am\n1600 Invented Road\n$31.32 2 items",  # total
    "In-Store: September 19, 2026, 11:41 am\n1602 Invented Road\n$31.23 2 items",  # store
], ids=["kind", "date", "total", "store"])
def test_one_fact_differing_fits_nothing(tmp_path, monkeypatch, row):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    old = dict(app.progress.data[OLD_KEY])
    discover(app, monkeypatch, [row])
    assert app.progress.data[OLD_KEY] == old
    assert not is_held(app, key_of(row))
    assert key_of(row) in app.discovery.data and key_of(row) not in app.progress.data


def test_the_fallback_store_fits_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    no_store_old = "In-Store: 09/19/2026\n$31.23  6 items"
    no_store_new = "In-Store: September 19, 2026, 11:41 am\n$31.23 2 items"
    assert site.card_to_purchase(card(no_store_new)).items[0].name == "Meijer order"
    key, _ = put_saved(app, tmp_path, row=no_store_old)
    discover(app, monkeypatch, [no_store_new])
    assert key in app.progress.data and not is_held(app, key_of(no_store_new))


def test_fit_facts_needs_every_fact():
    good = old_record()
    assert mr.fit_facts(good) == (IN_STORE, "2026-09-19", "3123", "1600 invented road")
    for broken in (dict(good, purchase_date=""), dict(good, total=""), dict(good, total=31.23),
                   dict(good, items=[]), dict(good, items="x"), dict(good, items=["x"]),
                   dict(good, purchase_type="Pickup"), None, "text", []):
        assert mr.fit_facts(broken) is None


# -- lists read in part, and holds worked out again -------------------------

def test_a_list_cut_short_moves_nothing_and_holds_the_fit(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    old = dict(app.progress.data[OLD_KEY])
    discover(app, monkeypatch, [NEW_1141], read=(ONLINE,), unsettled=("In-Store Receipts",))
    assert app.progress.data[OLD_KEY] == old and NEW_KEY not in app.progress.data
    assert is_held(app, NEW_KEY)
    assert run_all(app, monkeypatch) == []


def test_a_list_cut_short_retires_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    a = put_unsaved(app)
    b = put_unsaved(app, row=OTHER_OLD_ROW)
    discover(app, monkeypatch, [NEW_1141], read=(ONLINE,), unsettled=("In-Store Receipts",))
    assert a in app.discovery.data and b in app.discovery.data
    assert is_held(app, NEW_KEY)


def test_an_unread_tab_holds_only_its_own_kind(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141], read=(IN_STORE,), unread=("Online Orders",))
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True


def test_a_twin_whose_row_has_gone_still_counts_so_the_other_is_never_adopted(tmp_path, monkeypatch):
    """Review. Twins were held, then the 4:02 row went. The saved record
    may be the gone twin's, so the 11:41 purchase must not take it."""
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    discover(app, monkeypatch, [NEW_1141])
    assert OLD_KEY in app.progress.data and NEW_KEY not in app.progress.data
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    assert run_all(app, monkeypatch) == []


def test_holds_are_cleared_and_worked_out_again_on_a_whole_read(tmp_path, monkeypatch):
    """Twins of an unsaved old record and a saved one were held. Once the
    saved one is gone from the group (its record holds nothing now), the
    next whole read clears the holds and the twins download."""
    app = make_app(tmp_path)
    saved, _ = put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    for store in (app.progress.data, app.discovery.data):
        for f in ("downloaded_ok", "pdf_path", "pdf_filename"):
            store[saved].pop(f, None)
        store[saved]["state"] = "Failed"
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert not is_held(app, NEW_KEY) and not is_held(app, TWIN_KEY)
    assert saved not in app.discovery.data
    assert sorted(run_all(app, monkeypatch)) == sorted([NEW_KEY, TWIN_KEY])


def test_a_hold_before_a_later_start_date_stays(tmp_path, monkeypatch):
    """Review. A run scoped to start after the held day must not clear the
    hold, or a Resume with no start date presses both twins."""
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    app.args.start_date = "2026-09-20"
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    app.args.start_date = None
    assert run_all(app, monkeypatch) == []


def test_an_adopted_unsaved_record_takes_the_rows_words(tmp_path, monkeypatch):
    """Review. The row is looked for by its store's words as printed, so a
    record never saved takes them. A saved one keeps its own."""
    app = make_app(tmp_path)
    put_unsaved(app, row="In-Store: 09/19/2026\n1600 INVENTED ROAD\n$31.23  6 items")
    discover(app, monkeypatch, [NEW_1141])
    assert app.discovery.data[NEW_KEY]["items"][0]["name"] == "1600 Invented Road"
    app2 = make_app(tmp_path / "saved")
    put_saved(app2, tmp_path / "saved", row="In-Store: 09/19/2026\n1600 INVENTED ROAD\n$31.23  6 items")
    discover(app2, monkeypatch, [NEW_1141])
    assert app2.progress.data[NEW_KEY]["items"][0]["name"] == "1600 INVENTED ROAD"


@pytest.mark.parametrize("later_row,adopted", [
    (ELSEWHERE, False),
    ("Online: September 17, 2026, 2:15 pm\n9 Invented Lane\n$5.10 1 items", True),
], ids=["same-kind-on-page-two", "other-kind-on-page-two"])
def test_a_kind_past_its_first_page_is_never_read_whole(tmp_path, monkeypatch, later_row, adopted):
    """Review. A later page that did not load ends the list as a last page
    does, so a kind that went on past its first page moves nothing. A kind
    wholly on the first page still adopts (re-check)."""
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    pages = {2: [card(later_row)]}
    discover(app, monkeypatch, [NEW_1141])
    app2 = make_app(tmp_path / "paged")
    put_saved(app2, tmp_path / "paged")
    calls = {"n": 1}

    def later(page, *a, **k):
        calls["n"] += 1
        return pages.get(calls["n"], [])

    monkeypatch.setattr(mr.App, "page", lambda self: object())
    monkeypatch.setattr(mr.App, "_open_orders", lambda self, page: None)
    monkeypatch.setattr(mr.App, "check_session", lambda self, page: False)

    def both(page, facts=None):
        facts.update({"read": [IN_STORE, ONLINE], "unsettled": [], "unread": []})
        return [card(NEW_1141)]

    monkeypatch.setattr(site, "collect_both_tabs", both)
    monkeypatch.setattr(site, "goto_orders", lambda page, n=1: True)
    monkeypatch.setattr(site, "collect_cards", later)
    app2._list_cut_short = False
    app2.cmd_discover(quiet=True, finish=False)
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True
    if adopted:
        assert OLD_KEY not in app2.progress.data and not is_held(app2, NEW_KEY)
        assert app2.progress.data[NEW_KEY]["downloaded_ok"] is True
    else:
        assert OLD_KEY in app2.progress.data and is_held(app2, NEW_KEY)


def test_csv_rows_under_the_old_number_go_when_an_adopted_record_is_saved(tmp_path, monkeypatch):
    """Review. A record no longer listed wrote its rows under the number it
    had on the earlier page, and they are its rows after it moves."""
    app = make_app(tmp_path)
    put_unsaved(app, progress={"state": "No Longer Listed", mr.UNLISTED_ROWS: True})
    old_no = OLD_KEY.split(":", 1)[1]
    for book in (app.order_csv, app.index_csv):
        book.rewrite([{"Purchase Type": IN_STORE, "Order or Receipt Number": old_no,
                       "Processing Status": "No Longer Listed"}])
    discover(app, monkeypatch, [NEW_1141])
    app._forget_unlisted_rows(Purchase.from_dict(app.discovery.data[NEW_KEY]))
    for book in (app.order_csv, app.index_csv):
        assert book.read_all() == []


def test_an_old_key_listed_again_is_never_moved_by_the_repair(tmp_path, monkeypatch):
    """Review. The repair of a move a stopped run left half done only ever
    finishes a move, never takes a record whose own row is listed."""
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141])
    app.discovery.data[OLD_KEY] = old_record(state="Discovered")
    discover(app, monkeypatch, [OLD_ROW, NEW_1141])
    assert app.discovery.data[OLD_KEY]["order_number"] == OLD_KEY.split(":", 1)[1]
    assert app.discovery.data[NEW_KEY]["downloaded_ok"] is True


def test_a_hold_from_a_list_read_in_part_is_adopted_on_the_next_whole_read(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141], read=(ONLINE,), unsettled=("In-Store Receipts",))
    assert is_held(app, NEW_KEY)
    discover(app, monkeypatch, [NEW_1141])
    assert not is_held(app, NEW_KEY)
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True
    assert run_all(app, monkeypatch) == []


# -- holds in the purchase loop ---------------------------------------------

def test_a_held_purchase_is_skipped_in_fixed_words(tmp_path, monkeypatch, capsys):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    capsys.readouterr()
    assert run_all(app, monkeypatch) == []
    out = [ln for ln in capsys.readouterr().out.splitlines() if "Held." in ln]
    assert len(out) == 2
    for ln in out:
        assert not any(ch.isdigit() for ch in ln) and "Invented" not in ln
    assert app.stats["held"] == 2


def test_redownload_fetches_a_held_purchase(tmp_path, monkeypatch):
    app = make_app(tmp_path, redownload=True)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)
    assert set(run_all(app, monkeypatch)) >= {NEW_KEY, TWIN_KEY}


# -- retirement -------------------------------------------------------------

@pytest.mark.parametrize("sign", [
    ("progress", {"downloaded_ok": True}), ("progress", {"pdf_path": "x.pdf"}),
    ("progress", {"pdf_filename": "x.pdf"}), ("discovery", {"pdf_path": "x.pdf"}),
    ("discovery", {"pdf_filename": "x.pdf"}), ("progress", {"state": "Completed"}),
    ("progress", {"state": "PDF Verified"}), ("progress", {"state": "Canceled"}),
    ("progress", {"state": "Needs Manual Review"}),
], ids=lambda s: "%s-%s" % (s[0], "-".join("%s" % v for v in s[1].values())))
def test_each_sign_of_a_saved_record_keeps_it_from_retirement(tmp_path, monkeypatch, sign):
    app = make_app(tmp_path)
    where, fields = sign
    put_unsaved(app, progress={"state": "Failed"})
    getattr(app, where).data[OLD_KEY].update(fields)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert OLD_KEY in app.discovery.data
    assert is_held(app, NEW_KEY) and is_held(app, TWIN_KEY)


@pytest.mark.parametrize("state", ["Discovered", "Details Extracted", "Receipt Located",
                                   "Failed", "No Receipt Available", "No Longer Listed"])
def test_a_record_holding_nothing_is_retired(tmp_path, monkeypatch, state):
    app = make_app(tmp_path)
    put_unsaved(app, progress={"state": state})
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert OLD_KEY not in app.discovery.data and OLD_KEY in app.progress.data
    assert not is_held(app, NEW_KEY)


# -- records already under new keys, and old-layout pages -------------------

def test_records_already_under_new_keys_are_untouched(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    for row, extra in ((NEW_1141, {"state": "Completed", "downloaded_ok": True}),
                       (NEW_0402, {"state": "Failed"})):
        rec = dict(site.card_to_purchase(card(row)).to_dict(), **extra)
        app.progress.data[key_of(row)] = dict(rec)
        app.discovery.data[key_of(row)] = dict(rec)
    before = json.dumps(app.progress.data, sort_keys=True)
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert json.dumps(app.progress.data, sort_keys=True) == before
    assert not list(app.paths.backups.glob("*.bak")) if app.paths.backups.exists() else True


def test_a_marked_record_whose_row_is_gone_is_never_an_old_layout_record(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    rec = dict(site.card_to_purchase(card(NEW_1141)).to_dict(), state="Completed",
               downloaded_ok=True, **{ROW_PRINTS_TIME: True})
    app.progress.data[NEW_KEY] = dict(rec)
    app.discovery.data[NEW_KEY] = dict(rec)
    discover(app, monkeypatch, [NEW_0402])
    assert app.progress.data[NEW_KEY]["order_number"] == NEW_KEY.split(":", 1)[1]
    assert NEW_KEY in app.discovery.data
    assert TWIN_KEY not in app.progress.data and not is_held(app, TWIN_KEY)


def test_a_record_named_by_its_date_line_is_never_adopted(tmp_path, monkeypatch):
    """The contributor's commit named a purchase of the new page by its date
    line (R1 of the first review), and its record carries no marker. That
    name is no store line, so even with its row gone it fits nothing."""
    app = make_app(tmp_path)
    rec = dict(site.card_to_purchase(card(NEW_1141)).to_dict(), state="Completed", downloaded_ok=True)
    rec["items"][0]["name"] = "In-Store: September 19, 2026, 11:41 am"
    app.progress.data[NEW_KEY] = dict(rec)
    app.discovery.data[NEW_KEY] = dict(rec)
    discover(app, monkeypatch, [NEW_0402])
    assert app.progress.data[NEW_KEY]["order_number"] == NEW_KEY.split(":", 1)[1]
    assert TWIN_KEY not in app.progress.data and not is_held(app, TWIN_KEY)


def test_a_record_listed_under_its_own_key_is_never_an_old_layout_record(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [OLD_ROW, NEW_1141])
    assert app.progress.data[OLD_KEY]["downloaded_ok"] is True
    assert NEW_KEY not in app.progress.data and not is_held(app, NEW_KEY)


def test_an_old_layout_page_adopts_holds_marks_and_retires_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    other = put_unsaved(app, row=OTHER_OLD_ROW)
    old_elsewhere = "In-Store: 09/18/2026\n77 Example Street\n$12.80  3 items"
    discover(app, monkeypatch, [old_elsewhere])
    assert OLD_KEY in app.discovery.data and other in app.discovery.data
    for rec in app.discovery.data.values():
        assert HELD not in rec and ROW_PRINTS_TIME not in rec and ADOPTED_FROM not in rec


def test_listing_a_timed_row_marks_its_record_new_or_already_there(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    app.discovery.data[NEW_KEY] = dict(site.card_to_purchase(card(NEW_1141)).to_dict(), state="Discovered")
    discover(app, monkeypatch, [NEW_1141, NEW_0402])
    assert app.discovery.data[NEW_KEY][ROW_PRINTS_TIME] is True
    assert app.discovery.data[TWIN_KEY][ROW_PRINTS_TIME] is True


# -- adverse cases ----------------------------------------------------------

def test_an_interrupted_adoption_converges_and_never_presses_again(tmp_path, monkeypatch):
    """Progress is written first. A run stopped before discovery is written
    leaves the receipt done under its new key, and the next discovery
    finishes the move, so the old key is never pressed and never fails."""
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    write_stores(app)
    real = storage.JsonStore.save
    calls = {"n": 0}

    def failing(self, backup=False, leaving=False):
        if self is app.discovery and backup:
            calls["n"] += 1
            raise OSError("invented failure to write")
        return real(self, backup=backup, leaving=leaving)

    monkeypatch.setattr(storage.JsonStore, "save", failing)
    with pytest.raises(OSError):
        discover(app, monkeypatch, [NEW_1141])
    assert calls["n"] == 1
    monkeypatch.setattr(storage.JsonStore, "save", real)
    app2 = make_app(tmp_path)
    app2.progress.load()
    app2.discovery.load()
    assert app2.progress.data[NEW_KEY]["downloaded_ok"] is True
    assert OLD_KEY in app2.discovery.data
    discover(app2, monkeypatch, [NEW_1141])
    assert OLD_KEY not in app2.discovery.data
    assert app2.discovery.data[NEW_KEY]["downloaded_ok"] is True
    assert run_all(app2, monkeypatch) == []
    # The same when the list is read in part the next time.
    app3 = make_app(tmp_path / "again")
    put_saved(app3, tmp_path / "again")
    app3.progress.data[NEW_KEY] = dict(app3.progress.data.pop(OLD_KEY), order_number=NEW_KEY.split(":")[1],
                                       **{ADOPTED_FROM: OLD_KEY.split(":")[1]})
    discover(app3, monkeypatch, [NEW_1141], read=(ONLINE,), unsettled=("In-Store Receipts",))
    assert OLD_KEY not in app3.discovery.data and not is_held(app3, NEW_KEY)
    assert run_all(app3, monkeypatch) == []


def test_malformed_records_fit_nothing_and_are_left_as_they_are(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    junk = {"In-Store:pjunk1": "text", "In-Store:pjunk2": None, "In-Store:pjunk3": [],
            "In-Store:pjunk4": {}, "In-Store:pjunk5": {"items": "x"},
            "In-Store:pjunk6": dict(old_record(), order_number="pother")}
    for k, v in junk.items():
        app.discovery.data[k] = v
        app.progress.data[k] = v
    discover(app, monkeypatch, [NEW_1141])
    for k, v in junk.items():
        assert app.progress.data[k] == v
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True


def test_a_progress_only_old_record_is_adopted_from_progress(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    del app.discovery.data[OLD_KEY]
    discover(app, monkeypatch, [NEW_1141])
    assert OLD_KEY not in app.progress.data
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True
    assert run_all(app, monkeypatch) == []


def test_a_second_discovery_changes_nothing(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    discover(app, monkeypatch, [NEW_1141])
    first = (json.dumps(app.progress.data, sort_keys=True),
             {k: {f: v for f, v in r.items() if f != "discovered_at"} for k, r in app.discovery.data.items()})
    discover(app, monkeypatch, [NEW_1141])
    assert (json.dumps(app.progress.data, sort_keys=True),
            {k: {f: v for f, v in r.items() if f != "discovered_at"} for k, r in app.discovery.data.items()}) == first


def test_an_adopted_no_longer_listed_record_is_tried_again(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_unsaved(app, progress={"state": "No Longer Listed"})
    discover(app, monkeypatch, [NEW_1141])
    assert app.progress.data[NEW_KEY]["state"] == "Discovered"
    assert run_all(app, monkeypatch) == [NEW_KEY]


def test_two_groups_on_one_page_are_judged_apart(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    other_old = "In-Store: 09/18/2026\n1602 Invented Road\n$40.00  6 items"
    put_saved(app, tmp_path, row=other_old, name="2026-09-18 Meijer Other Receipt.pdf")
    twins = ["In-Store: September 18, 2026, 9:00 am\n1602 Invented Road\n$40.00 1 items",
             "In-Store: September 18, 2026, 5:00 pm\n1602 Invented Road\n$40.00 1 items"]
    discover(app, monkeypatch, [NEW_1141] + twins)
    assert app.progress.data[NEW_KEY]["downloaded_ok"] is True
    assert all(is_held(app, key_of(t)) for t in twins)


# -- backups and privacy ----------------------------------------------------

def test_both_stores_are_backed_up_before_a_record_moves(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    write_stores(app)
    discover(app, monkeypatch, [NEW_1141])
    for stem in ("progress", "discovery"):
        backups = sorted(app.paths.backups.glob(stem + "*.bak"))
        assert backups, stem
        held = json.loads(backups[0].read_text(encoding="utf-8"))
        assert OLD_KEY in held and NEW_KEY not in held


def test_discovery_is_backed_up_before_a_record_is_retired(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    put_unsaved(app)
    b = put_unsaved(app, row=OTHER_OLD_ROW)
    write_stores(app)
    discover(app, monkeypatch, [NEW_1141])
    backups = sorted(app.paths.backups.glob("discovery*.bak"))
    held = json.loads(backups[0].read_text(encoding="utf-8"))
    assert OLD_KEY in held and b in held


def test_adoption_lines_carry_counts_and_fixed_words_only(tmp_path, monkeypatch, caplog, capsys):
    app = make_app(tmp_path)
    put_saved(app, tmp_path)
    twins_old = "In-Store: 09/18/2026\n1602 Invented Road\n$40.00  6 items"
    put_saved(app, tmp_path, row=twins_old, name="2026-09-18 Meijer Other Receipt.pdf")
    twins = ["In-Store: September 18, 2026, 9:00 am\n1602 Invented Road\n$40.00 1 items",
             "In-Store: September 18, 2026, 5:00 pm\n1602 Invented Road\n$40.00 1 items"]
    caplog.set_level(logging.INFO)
    discover(app, monkeypatch, [NEW_1141] + twins)
    lines = [r.getMessage() for r in caplog.records] + capsys.readouterr().out.splitlines()
    about = [ln for ln in lines if any(w in ln.lower() for w in ("adopt", "held", "retire"))]
    assert about
    words = ("2026", "09/1", "September", "Invented", "1600", "1602", "31.23", "40.00",
             OLD_KEY.split(":")[1], NEW_KEY.split(":")[1], "In-Store:p")
    for ln in about:
        assert not any(w in ln for w in words), ln
    assert not any(ch.isdigit() for ch in HELD_REASON)


# -- an adopted record never saved is pressed on its own row ----------------

@pytest.fixture
def browse(monkeypatch):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    monkeypatch.setattr(site, "ROW_LOOKS", 1)
    opened = []
    orders = "https://www.meijer.com/shopping/orders"

    def open_page(html):
        ctx = browser.new_context(accept_downloads=True)
        ctx.route("**/*", lambda r: r.abort())
        ctx.route(orders, lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        pg = ctx.new_page()
        pg.goto(orders)
        opened.append(ctx)
        return pg

    yield open_page
    for ctx in opened:
        ctx.close()
    browser.close()
    driver.stop()


def _row_html(when, store, amount, who):
    return (f'<li class="order-card"><div class="date">In-Store: {when}</div><div>{store}</div>'
            f'<div class="totals"><span>{amount}</span>&nbsp;&nbsp;2 items</div>'
            f'<button type="button" aria-label="Download receipt from {when}" '
            f'onclick="window.pressed.push(\'{who}\')">&#8595;</button></li>')


def test_an_adopted_unsaved_record_finds_its_own_row_on_a_page_in_a_browser(tmp_path, monkeypatch, browse):
    html = ('<!doctype html><html><body><main><h1>Orders</h1><div role="tablist">'
            '<button role="tab">Online</button><button role="tab">In-Store</button></div><ul>'
            + _row_html("September 19, 2026, 11:41 am", "1600 Invented Road", "$31.23", "mine")
            + _row_html("September 18, 2026, 9:05 am", "77 Example Street", "$12.80", "other")
            + '</ul><script>window.pressed = [];</script></main></body></html>')
    pg = browse(html)
    rows = [c.text for c in site.collect_cards(pg)]
    app = make_app(tmp_path)
    put_unsaved(app, progress={"state": "Failed"})
    old = Purchase.from_dict(app.discovery.data[OLD_KEY])
    # Before, the record was looked for by its old key, which no row gives.
    assert site.own_when(pg, old) == ("", None, True)
    discover(app, monkeypatch, rows)
    adopted = next(p for p in app._select_purchases(IN_STORE, limit=0)
                   if p.purchase_date == "2026-09-19")
    assert adopted.key != OLD_KEY
    assert site.own_when(pg, adopted)[1] == ("2026-09-19", "11:41")
    facts, trace = {}, []
    site.press_row_receipt(pg, adopted, trace, facts)
    assert pg.evaluate("window.pressed") == ["mine"]
