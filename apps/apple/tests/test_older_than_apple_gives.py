"""Apple refuses an account's oldest receipts, from a line that differs by
account (#55).

RECORDED. Report a Problem refused every purchase before October 2016 on
the account this app was built on, before May 2015 on a tester's, and
anything older than eighteen months on another tester's, who asked for the
app to stop asking. Each refused purchase was asked again on every run, a
few seconds each, until its third refusal made a record of it.

Purchases go newest first. Once Apple has refused ten of an account's
purchases in a row, each older than any receipt it has given that account,
the older ones are not asked for the rest of the run, but for one a year
until Apple refuses it, and each counts as refused on that run, so a record
still waits for three separate runs. The run that would make a purchase's
record asks it, so every record rests on Apple's own refusal. Pending
purchases are checked on the next run that includes them. A receipt Apple
gives past the line takes it away, and --redownload asks everything.
Apple's process_purchases() runs on the harness of test_download_path.py.
Every order and name is invented.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import apple_site as site
import test_download_path as harness
from paperpull_core.models import Purchase, State

ACCOUNT, OTHER = "10000001", "10000002"


def _month(i):
    """The i-th month back from June 2026, as a purchase date."""
    y, m = 2026, 6 - i
    while m <= 0:
        y, m = y - 1, m + 12
    return "%d-%02d-15" % (y, m)


def _rows(given, refused, then_given=0, account=ACCOUNT, start=0, prefix="MLF"):
    """`given` newest purchases Apple gives, then `refused` older ones it
    refuses, then `then_given` older still that it gives again."""
    rows, answers = [], {}
    for n in range(given + refused + then_given):
        order = "%s%07d" % (prefix, start + n)
        rows.append(harness.app_store(order, account, date=_month(start + n)))
        if given <= n < given + refused:
            answers[order] = harness.REFUSED
    return rows, answers


def _app(tmp_path, monkeypatch, rows, answers):
    app, spy, failures, asked, run = harness._runs(tmp_path, monkeypatch, rows, answers)
    delays = []
    app._delay = lambda *a, **kw: delays.append(1)
    return app, spy, asked, run, delays


def _orders(asked):
    return [order for order, _dsid in asked]


def _prog(app, order):
    return app.progress.get("App Store:" + order)


def test_past_ten_refusals_older_than_any_receipt_the_older_ones_are_not_asked(tmp_path,
                                                                               monkeypatch):
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    orders = [p.order_number for p, _rec in rows]
    # Three given, ten refused in a row, then only December 2024, the newest
    # of the next year, is asked.
    probe = orders[3 + 10 + 5]
    assert _month(3 + 10 + 5) == "2024-12-15"
    assert _orders(asked) == orders[:13] + [probe], _orders(asked)
    assert app.stats["not_asked"] == 14 and len(delays) == 14
    assert app.stats["failed"] == app.stats["no_receipt"] == 11
    for order in orders[3:]:
        done = _prog(app, order)
        quiet = order not in orders[:13] + [probe]
        assert done["state"] == (State.DISCOVERED.value if quiet else State.FAILED.value), order
        assert done["refused_runs"] == ["run-1"], order
        assert done["not_asked_runs"] == (["run-1"] if quiet else []), order
    assert spy.calls and all(c.arguments["expect"].number in orders[:3] for c in spy.calls)


def test_a_record_still_waits_for_three_runs_and_rests_on_apples_own_refusal(tmp_path,
                                                                             monkeypatch):
    """On the second run the same refusal line comes back, but every
    deferred purchase is asked. A third run still makes the record only
    when Apple refuses the individual receipt."""
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    orders = [p.order_number for p, _rec in rows]
    run("run-1")
    assert len(asked) == 14
    # The same fallback metadata was marked Failed in older versions.
    for order in orders[3:]:
        record = _prog(app, order)
        if record.get("not_asked_runs"):
            record["state"] = State.FAILED.value
    run("run-2")
    assert all(_prog(app, o)["state"] == State.FAILED.value for o in orders[3:])
    assert set(_orders(asked[14:])) == set(orders)
    assert not app.stats.get("purchase_records")
    run("run-3")
    assert set(_orders(asked[14 + len(orders):])) == set(orders)
    for order in orders[3:]:
        done = _prog(app, order)
        assert done["state"] == State.COMPLETED.value, order
        assert done["document_type"] == site.RECORD_TYPE, order
        assert done["refused_runs"] == ["run-1", "run-2", "run-3"], order
    assert _prog(app, orders[-1])["not_asked_runs"] == ["run-1"]
    assert _prog(app, orders[3])["not_asked_runs"] == []


def test_a_deferred_purchase_can_get_its_receipt_even_when_the_same_refusals_continue(
        tmp_path, monkeypatch):
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    target = rows[15][0].order_number
    run("run-1")
    assert target not in _orders(asked)
    assert _prog(app, target)["state"] == State.DISCOVERED.value

    fetch = site.fetch_invoice

    def answer_one(page, order_number, dsid):
        if order_number != target:
            return fetch(page, order_number, dsid)
        asked.append((order_number, dsid))
        return {"kind": site.ANSWERED, "status": 200, "html": harness.RECEIPT_HTML % target}

    monkeypatch.setattr(site, "fetch_invoice", answer_one)
    app._already_done = lambda purchase: type(app)._already_done(app, purchase)
    checked = len(asked)
    run("run-2")
    rechecked = _orders(asked[checked:])
    assert target in rechecked
    assert all(p.order_number in rechecked for p, _ in rows[3:13])
    assert not any(p.order_number in rechecked for p, _ in rows[:3])
    saved = _prog(app, target)
    assert saved["state"] == State.COMPLETED.value and saved["downloaded_ok"]
    assert saved["document_type"] == "Receipt"
    assert any(c.arguments["expect"].number == target for c in spy.calls)


def test_a_receipt_given_past_the_line_takes_it_away(tmp_path, monkeypatch, capsys):
    """Twelve refused in the middle of the history and older ones Apple gives.
    The newest of the next year is asked, Apple gives it, and the rest are
    asked. The few the line passed over that run are asked on the next,
    which starts from the older receipt, and are saved."""
    rows, answers = _rows(given=2, refused=12, then_given=8)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    orders = [p.order_number for p, _rec in rows]
    run("run-1")
    passed_over = [o for o, (p, _r) in zip(orders, rows)
                   if p.purchase_date.startswith("2025") and o not in answers]
    assert passed_over and all(_prog(app, o)["not_asked_runs"] == ["run-1"] for o in passed_over)
    later = [o for o, (p, _r) in zip(orders, rows) if p.purchase_date.startswith("2024")]
    assert set(later) <= set(_orders(asked)), "asked again once Apple gave December 2024"
    assert "older purchases are asked again" in capsys.readouterr().out
    before = len(asked)
    run("run-2")
    assert len(asked) - before == len(orders), "the second run asks every one"
    for order in passed_over:
        done = _prog(app, order)
        assert done["state"] == State.COMPLETED.value and done["document_type"] == "Receipt"


def test_redownload_asks_every_purchase(tmp_path, monkeypatch):
    """--redownload asks Apple for every receipt once more, as the README
    says, so no purchase is past a line then (review)."""
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    app.args = SimpleNamespace(redownload=True)
    run("run-1")
    assert len(asked) == len(rows) and not app.stats["not_asked"]


def test_a_year_whose_newest_got_no_answer_is_asked_again(tmp_path, monkeypatch):
    """December 2024's purchase got no answer at all, which says nothing
    about the receipt, so November's is asked, Apple refuses it, and only
    then is the rest of 2024 left unasked (review)."""
    rows, answers = _rows(given=3, refused=25)
    orders = [p.order_number for p, _rec in rows]
    answers[orders[18]] = {"kind": site.FAILED, "status": 0, "html": ""}
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    assert _month(18) == "2024-12-15" and _month(19) == "2024-11-15"
    assert _orders(asked) == orders[:13] + [orders[18], orders[19]], _orders(asked)
    assert app.stats["not_asked"] == 13


def test_a_receipt_of_no_known_account_counts_for_every_account(tmp_path, monkeypatch):
    """A receipt from 2016 is on file under a key discovery no longer has,
    so whose it was is not known. It counts for every account, and twelve
    refusals from 2021 are no line (review)."""
    rows, answers = _rows(given=0, refused=12, start=60)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    app.progress.data["App Store:MLFGONE0001"] = {
        "purchase_type": "App Store", "purchase_date": "2016-11-21", "document_type": "Receipt",
        "downloaded_ok": True, "state": State.COMPLETED.value}
    run("run-1")
    assert len(asked) == 12 and not app.stats["not_asked"]


def test_a_refusal_newer_than_the_oldest_receipt_given_never_counts(tmp_path, monkeypatch):
    """A receipt from 2016 is on file, so Apple refusing twelve from 2021
    says nothing about a line, and every one is asked."""
    rows, answers = _rows(given=0, refused=12, start=60)
    old = harness.app_store("MLFOLD0001", ACCOUNT, date="2016-11-21")
    rows.append(old)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    app.progress.data["App Store:MLFOLD0001"] = {
        "purchase_type": "App Store", "purchase_date": "2016-11-21", "document_type": "Receipt",
        "downloaded_ok": True, "state": State.COMPLETED.value}
    run("run-1")
    assert len(asked) == 13 and not app.stats["not_asked"]


def test_an_account_apple_has_given_nothing_is_asked_in_full(tmp_path, monkeypatch):
    rows, answers = _rows(given=0, refused=14)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    assert len(asked) == 14 and not app.stats["not_asked"]


def test_one_accounts_line_is_its_own(tmp_path, monkeypatch):
    """A family's purchases are searched under each member's dsid. The
    organizer's line does not keep the other member's purchases from Apple."""
    mine, answers = _rows(given=1, refused=10)
    theirs, _ = _rows(given=6, refused=0, account=OTHER, start=11, prefix="MLG")
    extra, more = _rows(given=0, refused=4, start=17, prefix="MLH")
    rows = mine + theirs + extra
    answers.update(more)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    theirs_orders = [p.order_number for p, _r in theirs]
    assert set(theirs_orders) <= set(_orders(asked))
    assert app.stats["not_asked"] == 3, "of the organizer's four past the line, the year's newest is asked"


def test_the_line_is_learned_anew_each_run(tmp_path, monkeypatch):
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    first = len(asked)
    # Apple gives every receipt now. A line kept from the first run would
    # still keep most of them from being asked.
    monkeypatch.setattr(site, "fetch_invoice", lambda page, weborder, dsid: (
        asked.append((weborder, dsid))
        or {"kind": site.ANSWERED, "status": 200, "html": harness.RECEIPT_HTML % weborder}))
    run("run-2")
    assert len(asked) - first == len(rows), "Apple gives them all now, and all are asked"
    assert all(_prog(app, p.order_number)["state"] == State.COMPLETED.value for p, _r in rows)


def test_receipts_apple_never_gives_end_in_records_on_the_third_run_and_are_asked_no_more(
        tmp_path, monkeypatch):
    """Asking a purchase passed over on the run before has a cost Apple
    pays every run it is not bounded (#55). A purchase is passed over at
    most once, so a history Apple never gives is asked on three runs at
    most, ends as records on the third, and the fourth asks nothing. Every
    ask is paced, and a receipt saved on the first run is never asked again
    (review of #237)."""
    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, delays = _app(tmp_path, monkeypatch, rows, answers)
    app._already_done = type(app)._already_done.__get__(app)
    orders = [p.order_number for p, _rec in rows]
    per_run = []
    for key in ("run-1", "run-2", "run-3", "run-4"):
        before, paced = len(asked), len(delays)
        run(key)
        per_run.append(len(asked) - before)
        assert len(delays) - paced == per_run[-1], key
        assert not set(orders[:3]) & set(_orders(asked[before:])) or key == "run-1", key
    assert per_run == [14, 25, 25, 0], per_run
    for order in orders[3:]:
        done = _prog(app, order)
        assert done["state"] == State.COMPLETED.value, order
        assert done["document_type"] == site.RECORD_TYPE, order
        assert done["refused_runs"] == ["run-1", "run-2", "run-3"], order
        assert len(done["not_asked_runs"]) <= 1, order
        assert set(done["refused_runs"]) - set(done["not_asked_runs"]), order
    for order in orders[:3]:
        assert _prog(app, order)["document_type"] == "Receipt"
    assert app.stats["purchase_records"] == 25


def _summary(app, tmp_path, monkeypatch, capsys):
    app.paths.run_summary = tmp_path / "run-summary.txt"
    monkeypatch.setattr(harness.app_mod, "report_run_result", lambda stats: None)
    capsys.readouterr()
    app.write_run_summary()
    return capsys.readouterr().out


def test_the_end_of_the_run_says_how_many_were_left_pending(tmp_path, monkeypatch, capsys):
    """The purchases passed over are no longer counted failed, so the end of
    the run says how many wait for the next, in words that fit one as well
    as many (review of #237)."""
    rows, answers = _rows(given=3, refused=11)
    app, spy, asked, run, _delays = _app(tmp_path, monkeypatch, rows, answers)
    run("run-1")
    assert app.stats["not_asked"] == 1 and app.stats["failed"] == 10
    out = _summary(app, tmp_path, monkeypatch, capsys)
    assert ("1 older App Store purchase was left pending. A download run covering "
            "its date will ask Apple for its receipt.") in out, out
    assert "Older, not asked:          1" in (tmp_path / "run-summary.txt").read_text()

    rows, answers = _rows(given=3, refused=25)
    app, spy, asked, run, _delays = _app(tmp_path / "many", monkeypatch, rows, answers)
    run("run-1")
    out = _summary(app, tmp_path, monkeypatch, capsys)
    assert ("14 older App Store purchases were left pending. A download run covering "
            "their dates will ask Apple for their receipts.") in out, out


def test_a_record_of_a_purchase_not_asked_says_so():
    purchase = Purchase(purchase_type="App Store", purchase_date="2015-03-01",
                        order_number="MLF0TEST09", total="$6.99")
    page = site.purchase_record_html(purchase, [], "", 3, made_on="2026-10-02", not_asked=2)
    assert "This is not Apple's receipt" in page
    assert "did not give the receipt for this purchase on 3 separate runs" in page
    assert "On 2 of them it was not asked" in page
    assert "already refused %d of this account's newer purchases in a row" % \
        site.REFUSAL_STREAK in page
    assert "on the last it refused this receipt itself" in page
    plain = site.purchase_record_html(purchase, [], "", 3, made_on="2026-10-02")
    assert "would not give the receipt for this purchase on 3 separate runs" in plain
    assert "not asked" not in plain
