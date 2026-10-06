"""How a business account's list is read, report by report. No browser.

The tester's recording kept the keys of each report in the list and none of
their values, so how PayPal writes a status, a kind of file or a period is
not known. These hold the rules the app reads them by, and above all what it
refuses. A value it cannot read leaves its statement alone and written
down, and is never guessed past. Every value here is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import paypal_site as site

AUGUST = ("2031-08-01", "2031-08-31")


@pytest.mark.parametrize("written", [
    "Aug 1, 2031 - Aug 31, 2031", "August 1, 2031 to August 31, 2031",
    "2031-08-01 to 2031-08-31", "08/01/2031 - 08/31/2031", "1 Aug 2031 - 31 Aug 2031",
    "20310801000000-20310831235959", "20310801-20310831",
    "2031-08-01T07:00:00Z/2031-08-31T23:59:59Z",
    {"startDate": "2031-08-01", "endDate": "2031-08-31"}, {"from": "08/01/2031", "to": "08/31/2031"},
    ["2031-08-01", "2031-08-31"], "August 2031", "Aug 2031", "08/2031", "2031-08",
])
def test_a_duration_is_read_as_its_first_and_last_day(written):
    assert site.period_of({"duration": written}) == site.Period(*AUGUST)


@pytest.mark.parametrize("written", [
    "Aug 31, 2031", "Aug 1 - Aug 31, 2031", "2031-08-31 to 2031-08-01",
    "2031-02-30 to 2031-03-01", "1999-08-01 to 1999-08-31", "2031-08-01 to 2031-08-15 to 2031-08-31",
    1785542400000, 31, {"start": "2031-08-01"}, {"start": 1785542400000, "end": 1788134400000},
    ["2031-08-01"], "August 2031 and September 2031",
])
def test_a_duration_this_app_cannot_read_is_refused_never_guessed(written):
    """A single day, a period ending before it starts, a day that does not
    exist, a count of milliseconds, one end of a pair. Its made day is not
    used in its place, since a duration with a number in it was meant to
    say the period."""
    assert site.period_of({"duration": written, "createdOn": "2031-09-02"}) is None


def test_a_duration_naming_no_day_at_all_leaves_the_day_it_was_made():
    made = site.Period(created="2031-09-02")
    assert site.period_of({"duration": "MONTHLY", "createdOn": "2031-09-02T10:15:00Z"}) == made
    assert site.period_of({"createdOn": "Sep 2, 2031"}) == made
    assert site.period_of({"duration": "", "createdOn": 1788307200000}) is None
    assert site.period_of({"duration": None}) is None


def test_a_statement_known_only_by_the_day_it_was_made_is_never_checked_against_it():
    made = site.Period(created="2031-09-02")
    assert made.identity() is None, "nothing says a statement prints the day it was made"
    assert made.date == "2031-09-02" and made.title() == "Statement - created 2031-09-02"


@pytest.mark.parametrize("status", ["COMPLETED", "Ready", "AVAILABLE", "Success",
                                    {"code": "COMPLETED"}, ["READY"]])
def test_a_status_that_says_ready_is_ready(status):
    assert site.status_of({"reportStatus": status}) == site.READY


@pytest.mark.parametrize("status", ["NOT_READY", "IN_PROGRESS", "inProgress", "FAILED",
                                    "EXPIRED", "PENDING", "COMPLETED_WITH_ERRORS", "Not available",
                                    "REQUESTED", "CANCELLED"])
def test_a_status_with_any_word_against_it_is_not_ready(status):
    assert site.status_of({"reportStatus": status}) == site.NOT_READY


@pytest.mark.parametrize("status", ["", None, "Zorvexquill", 3, ["9"], {"code": 7}])
def test_a_status_this_app_cannot_read_is_neither(status):
    assert site.status_of({"reportStatus": status}) == ""


@pytest.mark.parametrize("kind,read", [("PDF", "pdf"), ("pdf", "pdf"), ({"type": "PDF"}, "pdf"),
                                       ("CSV", "other"), ("PDF_CSV", "other"),
                                       ("TAB_DELIMITED", "other"), ("Excel", "other"),
                                       ("", ""), (None, ""), (4, "")])
def test_a_kind_of_file_is_a_pdf_only_when_it_says_pdf_and_nothing_else(kind, read):
    assert site.type_of({"fileFormat": kind}) == read


def test_a_report_is_read_kind_first_then_status_then_days():
    row = {"fileFormat": "PDF", "reportStatus": "COMPLETED", "duration": "Aug 1, 2031 - Aug 31, 2031"}
    assert site.read_row(row) == (site.READY, site.Period(*AUGUST))
    assert site.read_row(dict(row, fileFormat="CSV", reportStatus="???"))[0] == site.OTHER_TYPE
    assert site.read_row(dict(row, fileFormat=None))[0] == site.UNREAD_TYPE
    assert site.read_row(dict(row, reportStatus="IN_PROGRESS"))[0] == site.NOT_READY
    assert site.read_row(dict(row, reportStatus="Zorvexquill"))[0] == site.UNREAD_STATUS
    assert site.read_row(dict(row, duration="Aug 31, 2031"))[0] == site.UNREAD_PERIOD
    assert site.read_row("not a report")[0] == site.UNREAD_TYPE


def test_what_a_refused_report_leaves_in_a_failure_file_is_words_never_its_id_or_days():
    row = {"id": "QZ4XKRWPT7MVN", "fileFormat": "PDF", "reportStatus": "Zorvex_quill",
           "duration": "Aug 1, 2031 - Aug 31, 2031"}
    facts = site.row_facts(row, site.UNREAD_STATUS)
    assert facts == {"reads_as": "unread status", "status": "zorvex quill", "type": "pdf",
                     "period": "named"}


def test_a_record_holds_a_statements_days_and_never_its_id():
    period = site.Period(*AUGUST)
    assert period.href() == "/reports/accountStatements#period=2031-08-01..2031-08-31"
    assert site.business_ref(period.href()) == period
    made = site.Period(created="2031-09-02")
    assert site.business_ref(made.href()) == made
    for other in ("/reports/accountStatements#period=2031-08-31..2031-08-01",
                  "/reports/accountStatements#period=2031-02-30..2031-03-01",
                  "/reports/accountStatements#id=QZ4XKRWPT7MVN",
                  "https://www.paypal.com/reports/accountStatements#period=2031-08-01..2031-08-31",
                  "/myaccount/statements/api/statements/download?monthList=20310801&reportType=standard",
                  "", None):
        assert site.business_ref(other) is None, other


def test_a_month_is_titled_and_checked_as_a_month():
    period = site.Period(*AUGUST)
    assert period.title() == "Monthly Statement - August 2031"
    assert period.identity().date == "2031-08-31" and period.identity().period == "2031-08"
    odd = site.Period("2031-08-05", "2031-09-04")
    assert odd.title() == "Statement - 2031-08-05 to 2031-09-04"
    assert odd.identity().period == "", "a period across two months names neither"


def test_a_rows_words_name_its_days_only_as_dates_of_their_own():
    period = site.Period(*AUGUST)
    assert period.named_in("Monthly statement Aug 1, 2031 - Aug 31, 2031 PDF Ready") == 2
    assert period.named_in("August 2031") == 2 and period.named_in("08/2031") == 2
    assert period.named_in("Requested 08/31/2031") == 1
    assert period.named_in("Aug 11, 2031 - Aug 31, 2031") == 1, "the 1st found inside the 11th"
    assert period.named_in("Statement 2031-08-15") == 0, "an ISO day of the month is not the month"
    assert period.named_in("Jul 1, 2031 - Jul 31, 2031 Requested Aug 2, 2031") == 0
    assert site.Period(created="2031-09-02").named_in("Created Sep 2, 2031") == 2
