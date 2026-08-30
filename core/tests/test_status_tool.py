"""The status tool has to be right about what is overdue, or it is worse than
nothing. A tracker that cries wolf gets ignored, and one that stays quiet while
statements pile up defeats its own purpose.

Each test below pins a case that was wrong in the first working version, found
by running it against real installs.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

status = pytest.importorskip("status")


def _install(tmp_path, name, records, storage_src=None):
    d = tmp_path / name
    d.mkdir()
    (d / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    if storage_src:
        (d / "storage.py").write_text(storage_src, encoding="utf-8")
    return d


def _monthly(n, field="date", account="", end=None, gap=30):
    """n records one gap apart, newest `end` (default today)."""
    end = end or date.today()
    return {str(i): {field: (end - timedelta(days=gap * i)).isoformat(),
                     "account": account, "downloaded_ok": True,
                     "updated_at": "2026-01-01T00:00:00"}
            for i in range(n)}


# -- many accounts in one install, each monthly ------------------------------

def test_many_accounts_each_monthly_is_not_read_as_weekly(tmp_path):
    """A bank install can cover many accounts at once, each billed monthly.
    Pooling their dates makes the gaps look weekly, and the archive then
    calls itself overdue a week after a statement lands. Cadence is measured
    per account."""
    recs = {}
    for a in range(10):
        for i, (k, v) in enumerate(_monthly(12, account="acct%d" % a,
                                            end=date.today() - timedelta(days=a)).items()):
            recs["%d-%s" % (a, k)] = v
    d = _install(tmp_path, "Bank", recs, "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    row = status.scan_install(d)
    assert 25 <= row["cadence_days"] <= 35, row["cadence_days"]
    assert row["status"] == status.CURRENT


# -- receipt archives ---------------------------------------------------------

def test_receipt_archives_are_never_reported_as_overdue(tmp_path):
    """Purchases arrive irregularly. "You are 40 days overdue" would be noise."""
    d = _install(tmp_path, "Shop", _monthly(10, field="purchase_date",
                                            end=date.today() - timedelta(days=120)),
                 "SPEC = AppSpec(\n    kind=RECEIPT,\n)")
    row = status.scan_install(d)
    assert row["status"] == status.ONGOING
    assert row["newest"] is not None, "a receipt archive should still show its last purchase"


def test_a_second_account_folder_with_no_code_is_still_classified(tmp_path):
    """A --config second-account folder holds only data, so there is no spec to
    read. It was being treated as a statement archive with no dates at all,
    which reported it as unknown instead of ongoing."""
    d = _install(tmp_path, "Shop - someone", _monthly(8, field="purchase_date"))
    row = status.scan_install(d)
    assert row["kind"] == "RECEIPT"
    assert row["status"] == status.ONGOING
    assert row["newest"] == date.today()


def test_purchase_date_is_read_as_a_date(tmp_path):
    """Receipt apps date records with purchase_date, statement apps with date.
    Reading only `date` left every receipt archive showing no dates."""
    d = _install(tmp_path, "Shop", _monthly(5, field="purchase_date"))
    assert status.scan_install(d)["newest"] == date.today()


# -- the due / overdue thresholds --------------------------------------------

@pytest.mark.parametrize("age_days,expected", [
    (5, status.CURRENT),
    (30, status.CURRENT),
    (50, status.DUE),
    (95, status.OVERDUE),
])
def test_status_thresholds_for_a_monthly_provider(tmp_path, age_days, expected):
    recs = _monthly(12, end=date.today() - timedelta(days=age_days))
    d = _install(tmp_path, "Bank", recs, "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    assert status.scan_install(d)["status"] == expected


def test_a_yearly_provider_is_not_overdue_after_two_months(tmp_path):
    """An annual document six months old is normal. Judging it on a monthly
    assumption would flag half the archive permanently."""
    recs = _monthly(5, gap=365, end=date.today() - timedelta(days=200))
    d = _install(tmp_path, "Insurer", recs, "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    row = status.scan_install(d)
    assert row["status"] == status.CURRENT, row


def test_too_little_history_says_so_rather_than_guessing(tmp_path):
    d = _install(tmp_path, "New", _monthly(1), "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    assert status.scan_install(d)["status"] == status.UNKNOWN


def test_documents_that_were_never_downloaded_are_not_counted(tmp_path):
    recs = {"a": {"date": date.today().isoformat(), "downloaded_ok": False,
                  "state": "Discovered"}}
    d = _install(tmp_path, "Bank", recs, "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    row = status.scan_install(d)
    assert row["documents"] == 0 and row["newest"] is None


def test_a_folder_that_is_not_an_install_is_skipped(tmp_path):
    (tmp_path / "Not an install").mkdir()
    assert status.scan_install(tmp_path / "Not an install") is None


# -- the report itself --------------------------------------------------------

def test_the_dashboard_is_self_contained_and_leaks_no_figures(tmp_path):
    """It is written next to the installs and lists institutions, so it must
    pull in nothing from the network and carry no amounts."""
    d = _install(tmp_path, "Bank", _monthly(12), "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    rows = status.scan_all(tmp_path)
    out = tmp_path / "status.html"
    status.write_html(rows, out)
    html = out.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html.lower()
    assert "prefers-color-scheme" in html
    assert "Bank" in html


# -- only report archives that actually exist --------------------------------

def test_a_provider_you_do_not_use_is_not_listed(tmp_path):
    """Nobody holds an account with every provider. The report covers the
    archives that EXIST, not the providers that could exist, so an unused or
    closed-account folder is left out rather than shown as missing or overdue."""
    (tmp_path / "Never Set Up").mkdir()
    (tmp_path / "Closed Account" / ".").mkdir(parents=True)
    (tmp_path / "Closed Account" / "progress.json").write_text("{}", encoding="utf-8")
    used = _install(tmp_path, "In Use", _monthly(12),
                    "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    assert status.scan_install(tmp_path / "Never Set Up") is None
    assert status.scan_install(tmp_path / "Closed Account") is None
    rows = status.scan_all(tmp_path)
    assert [r["folder"] for r in rows] == ["In Use"]


def test_an_unreadable_state_file_is_reported_not_silently_dropped(tmp_path):
    """A truncated or corrupt progress.json used to make the whole provider
    vanish from the report. A run killed mid-write, a disk error or a partial
    sync would quietly remove an archive from oversight, which is the same
    silent loss this tool exists to catch."""
    d = tmp_path / "Corrupt"
    d.mkdir()
    (d / "progress.json").write_text('{"k": {"date": "2019-01-15", "downl',
                                     encoding="utf-8")
    row = status.scan_install(d)
    assert row is not None and row["status"] == status.UNREADABLE


def test_set_up_but_never_downloaded_says_so(tmp_path):
    """Documents were discovered but none fetched. That is the one state a
    single run fixes, so it is named rather than lumped in with unknown."""
    recs = {"a": {"date": date.today().isoformat(), "downloaded_ok": False,
                  "state": "Discovered"}}
    d = _install(tmp_path, "Fresh", recs, "SPEC = AppSpec(\n    kind=DOCUMENT,\n)")
    row = status.scan_install(d)
    assert row["status"] == status.NEVER
    assert row["documents"] == 0
    # and it is surfaced by --quiet, because it needs attention
    out = tmp_path / "status.html"
    status.write_html([row], out)
    assert "never downloaded" in out.read_text(encoding="utf-8")


# -- gaps in the MIDDLE of a history -----------------------------------------
# The failure this project keeps hitting: an archive looks current by its
# newest document while quietly missing whole periods behind it.

def _series(dates, account="", summary="Statement"):
    return [{"date": d.isoformat(), "downloaded_ok": True, "account": account,
             "summary": summary, "updated_at": "2026-01-01T00:00:00"}
            for d in dates]


def _months(n, skip=(), start=None, step=30):
    start = start or date(2020, 1, 15)
    return [start + timedelta(days=step * i) for i in range(n) if i not in skip]


def test_a_missing_month_in_a_monthly_series_is_found():
    recs = _series(_months(24, skip={10}))
    gaps = status.find_gaps(recs, "DOCUMENT")
    assert len(gaps) == 1
    assert gaps[0]["missing"] == 1


def test_several_consecutive_missing_months_are_counted():
    recs = _series(_months(24, skip={10, 11, 12}))
    gaps = status.find_gaps(recs, "DOCUMENT")
    assert len(gaps) == 1 and gaps[0]["missing"] == 3


def test_a_complete_series_reports_nothing():
    assert status.find_gaps(_series(_months(24)), "DOCUMENT") == []


def test_normal_jitter_is_not_a_gap():
    """Real statements drift by a few days either side of the cycle. Treating
    that as missing would make the report useless."""
    base = date(2020, 1, 10)
    drift = [0, 29, 62, 90, 121, 152, 179, 213, 240, 272, 301, 335, 365, 394]
    recs = _series([base + timedelta(days=d) for d in drift])
    assert status.find_gaps(recs, "DOCUMENT") == []


def test_an_irregular_series_is_left_alone():
    """Insurance ID cards and policy renewals arrive when they arrive. A long
    quiet stretch there means nothing was issued, not that something is
    missing, and flagging it would train you to ignore the report."""
    base = date(2020, 1, 1)
    irregular = [0, 16, 42, 119, 207, 365, 545, 731]
    recs = _series([base + timedelta(days=d) for d in irregular])
    assert status.find_gaps(recs, "DOCUMENT") == []


def test_receipts_are_never_gap_checked():
    recs = [{"purchase_date": d.isoformat(), "downloaded_ok": True, "account": "",
             "summary": "Groceries", "updated_at": "2026-01-01T00:00:00"}
            for d in _months(24, skip={5, 6, 7})]
    assert status.find_gaps(recs, "RECEIPT") == []


def test_a_short_history_is_not_judged():
    assert status.find_gaps(_series(_months(5)), "DOCUMENT") == []


def test_each_series_is_judged_separately():
    """One install can hold monthly statements and yearly tax forms at once.
    Pooling them would invent gaps in both."""
    recs = (_series(_months(24), summary="Monthly Statement")
            + _series(_months(4, step=365), summary="Yearly Tax Form"))
    assert status.find_gaps(recs, "DOCUMENT") == []


def test_only_downloaded_documents_count_towards_gaps():
    recs = _series(_months(24))
    for r in recs[8:12]:
        r["downloaded_ok"] = False
        r["state"] = "Discovered"
    gaps = status.find_gaps(recs, "DOCUMENT")
    assert gaps and gaps[0]["missing"] == 4, gaps


def test_the_same_window_across_accounts_is_reported_once():
    """One account missing a month is usually a quiet month. The same window
    missing across several accounts is a run that failed part way, and reads
    far better as one finding than as five."""
    recs = []
    for acct in ("A", "B", "C"):
        recs += _series(_months(24, skip={10}), account=acct)
    gaps = status.find_gaps(recs, "DOCUMENT")
    assert len(gaps) == 3
    grouped = status.group_gaps(gaps)
    assert len(grouped) == 1
    assert grouped[0]["count"] == 3 and grouped[0]["missing"] == 1


# -- what a red team found, each pinned so it cannot come back ---------------

def test_quiet_never_hides_a_gap(tmp_path):
    """--quiet is the mode meant for routine checking, and it was printing
    "everything is current" over an archive missing a whole year, because the
    gap section sat behind an early return."""
    import contextlib, io
    recs = {}
    for i, d in enumerate(_months(72)):
        if d.year == date.today().year - 4:
            continue
        recs[str(i)] = {"date": d.isoformat(), "downloaded_ok": True,
                        "account": "", "summary": "Statement",
                        "updated_at": "2026-01-01T00:00:00"}
    d = _install(tmp_path, "Bank", recs, "SPEC = AppSpec(kind=DOCUMENT)")
    rows = status.scan_all(tmp_path)
    assert rows[0]["missing"] > 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        status.print_table(rows, quiet=True)
    out = buf.getvalue()
    assert "Possible gaps" in out
    assert "Nothing needs attention" not in out


def test_a_future_dated_record_cannot_mask_a_stale_archive(tmp_path):
    """One record dated in the future made a five year hole report as current,
    and that date can come straight off a provider page."""
    recs = {str(i): {"date": d.isoformat(), "downloaded_ok": True, "account": "",
                     "summary": "S", "updated_at": "2026-01-01T00:00:00"}
            for i, d in enumerate(_months(30, start=date.today() - timedelta(days=2000)))}
    recs["evil"] = {"date": (date.today() + timedelta(days=95)).isoformat(),
                    "downloaded_ok": True, "account": "", "summary": "S",
                    "updated_at": "2026-01-01T00:00:00"}
    d = _install(tmp_path, "Stale", recs, "SPEC = AppSpec(kind=DOCUMENT)")
    assert status.scan_install(d)["status"] == status.OVERDUE


def test_one_odd_timestamp_does_not_kill_every_provider(tmp_path):
    """A record with a timezone offset next to one without raised TypeError,
    and it escaped scan_install to destroy the report for ALL providers."""
    recs = {"a": {"date": "2026-01-01", "downloaded_ok": True,
                  "updated_at": "2026-01-01T10:00:00"},
            "b": {"date": "2026-02-01", "downloaded_ok": True,
                  "updated_at": "2026-02-01T10:00:00+00:00"}}
    _install(tmp_path, "Poisoned", recs, "SPEC = AppSpec(kind=DOCUMENT)")
    _install(tmp_path, "Healthy", _monthly(12), "SPEC = AppSpec(kind=DOCUMENT)")
    assert len(status.scan_all(tmp_path)) == 2


def test_an_absurd_date_cannot_invent_thousands_of_missing_documents(tmp_path):
    """A single record dated year 0001 produced a finding of 24,000 missing
    documents. Noise on that scale trains you to skip the section, which has
    the same effect as hiding it."""
    recs = dict(_monthly(30))
    recs["ancient"] = {"date": "0001-01-01", "downloaded_ok": True, "account": "",
                       "summary": "S", "updated_at": "2026-01-01T00:00:00"}
    d = _install(tmp_path, "Bank", recs, "SPEC = AppSpec(kind=DOCUMENT)")
    assert status.scan_install(d)["missing"] == 0


def test_output_survives_text_the_console_cannot_encode(tmp_path):
    """Account labels are scraped, so they can hold characters the Windows
    console codepage cannot represent. Printing one killed the run before
    status.html was written."""
    import contextlib, io
    recs = dict(_monthly(12))
    for k in list(recs)[:2]:
        recs[k]["account"] = "Checking 中国 1234"
    _install(tmp_path, "Bank", recs, "SPEC = AppSpec(kind=DOCUMENT)")
    rows = status.scan_all(tmp_path)
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    with contextlib.redirect_stdout(stream):
        status.print_table(rows, quiet=False)
    stream.flush()


def test_the_launcher_blocks_both_execution_vectors():
    """status.bat is meant to live in a DATA folder, which is a plausible place
    for something else to drop a file. Without these, a planted py.bat runs
    instead of Python, and a planted statistics.py is imported instead of the
    real module."""
    bat = (REPO / "tools" / "status.bat").read_text(encoding="utf-8")
    assert "NoDefaultCurrentDirectoryInExePath=1" in bat
    assert "-P status.py" in bat
