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


def test_unreadable_state_is_skipped_rather_than_crashing(tmp_path):
    d = tmp_path / "Corrupt"
    d.mkdir()
    (d / "progress.json").write_text("{not json", encoding="utf-8")
    assert status.scan_install(d) is None


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
