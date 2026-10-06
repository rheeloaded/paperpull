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


def test_a_month_is_titled_as_a_month_and_any_other_range_by_its_days():
    assert site.Period(*AUGUST).title() == "Monthly Statement - August 2031"
    odd = site.Period("2031-08-05", "2031-09-04")
    assert odd.title() == "Statement - 2031-08-05 to 2031-09-04"


@pytest.mark.parametrize("days", [AUGUST, ("2031-07-01", "2031-08-31"),
                                  ("2031-08-05", "2031-08-20"), ("2031-08-31", "2031-08-31")])
def test_every_statement_is_checked_by_its_first_and_last_day_whatever_its_range(days):
    """The same two kinds of fact for a month and for any other range. A
    month that carried its month as well, beside a custom statement ending
    on the same day that carried only that day, kept its month once the
    shared day stopped counting, and the custom statement was refused when
    its text mentioned the month (review of 69dbec7)."""
    checked = site.Period(*days).identity()
    assert (checked.date, checked.start, checked.period) == (days[1], days[0], "")
    assert set(checked.strong()) == {"date", "start"}


def test_a_rows_words_name_its_days_only_as_dates_of_their_own():
    period = site.Period(*AUGUST)
    assert period.named_in("Monthly statement Aug 1, 2031 - Aug 31, 2031 PDF Ready") == 2
    assert period.named_in("August 2031") == 2 and period.named_in("Aug 2031") == 2
    assert period.named_in("Requested 08/31/2031") == 1
    assert period.named_in("Aug 11, 2031 - Aug 31, 2031") == 1, "the 1st found inside the 11th"
    assert period.named_in("Aug 01, 2031 - Aug 31, 2031") == 2
    assert period.named_in("Statement 2031-08-15") == 0, "an ISO day of the month is not the month"
    assert period.named_in("Jul 1, 2031 - Jul 31, 2031 Requested Aug 2, 2031") == 0
    assert site.Period(created="2031-09-02").named_in("Created Sep 2, 2031") == 2


def test_a_month_is_named_in_a_row_only_by_its_name():
    """July's 07/2031 is the end of the September day 09/07/2031 in
    August's row, and the ISO 2031-07 the front of every ISO day of July,
    so a row names a month by the month's name alone (review of c880958)."""
    july = site.Period("2031-07-01", "2031-07-31")
    assert july.named_in("08/01/2031 - 08/31/2031 09/07/2031 PDF Ready") == 0
    assert july.named_in("Statement 2031-07-15") == 0
    assert july.named_in("Period 07/2031") == 0 and july.named_in("Period 2031-07") == 0
    assert july.named_in("July 2031") == 2 and july.named_in("Jul 2031 PDF") == 2
    assert july.named_in("07/01/2031 - 07/31/2031 08/02/2031 PDF Ready") == 2


AUGUST_ROW = "Aug 1, 2031 - Aug 31, 2031 Sep 2, 2031 PDF Ready Download"
JULY_ROW = "Jul 1, 2031 - Jul 31, 2031 Aug 2, 2031 PDF Ready Download"
CUSTOM_ROW = "Jul 1, 2031 - Aug 31, 2031 Sep 3, 2031 PDF Ready Download"


def test_a_row_is_chosen_by_the_days_it_names_never_by_its_place():
    """A row naming another kind of file is never it. Of the rest, the one
    row naming the days, or the one naming them plainly where others name
    only the last day. Two naming them as plainly as each other are never
    told apart, whatever place the statement has in the list's answer."""
    aug = site.Period(*AUGUST)
    csv = "Aug 1, 2031 - Aug 31, 2031 Sep 2, 2031 CSV Ready Download CSV"
    assert site.choose_row([JULY_ROW, csv, AUGUST_ROW], aug) == (2, 2, "")
    assert site.choose_row([CUSTOM_ROW, AUGUST_ROW], aug) == (1, 2, "")
    assert site.choose_row([CUSTOM_ROW], aug) == (0, 1, "")
    assert site.choose_row([AUGUST_ROW, JULY_ROW, AUGUST_ROW], aug) == (-1, 0, site.MANY_ROWS)
    assert site.choose_row([CUSTOM_ROW, "Requested 08/31/2031 PDF"], aug) == \
        (-1, 0, site.MANY_ROWS)
    assert site.choose_row([JULY_ROW, csv], aug) == (-1, 0, site.NO_ROW)


def _view(*reports):
    view = site.Reports(None)
    view.take([(200, [{"reports": list(reports), "hasMore": False}])])
    return view


READY_PDF = {"fileFormat": "PDF", "reportStatus": "COMPLETED", "createdOn": "2031-09-02T10:15:00Z"}


def test_two_reports_naming_the_same_first_and_last_day_are_one_statement():
    listing = site.listing_of(_view(dict(READY_PDF, id="A", duration="Aug 1, 2031 - Aug 31, 2031"),
                                    dict(READY_PDF, id="B", duration="2031-08-01 to 2031-08-31",
                                         createdOn="2031-09-05T08:00:00Z")))
    assert [doc.href for doc in listing] == [site.Period(*AUGUST).href()]
    assert listing.unread == [] and listing.counts[site.UNREAD_SAME_DAY] == 0


def test_a_second_report_known_only_by_the_same_made_day_is_refused_and_written_down():
    """Two statements made on one day and naming no days of their own are
    not known to be one. Only one record was kept, and the other was let go
    of in silence. It is refused now, counted and written down."""
    listing = site.listing_of(_view(dict(READY_PDF, id="A", duration="MONTHLY"),
                                    dict(READY_PDF, id="B", duration="CUSTOM")))
    assert [doc.href for doc in listing] == [site.Period(created="2031-09-02").href()]
    assert [u["reads_as"] for u in listing.unread] == [site.UNREAD_SAME_DAY]
    assert listing.counts[site.READY] == 1 and listing.counts[site.UNREAD_SAME_DAY] == 1


@pytest.mark.parametrize("href,asked", [
    ("https://www.paypal.com/reports/apis/rux/reports/download/QZ4XKRWPT7MVN", True),
    ("https://www.paypal.com/myaccount/transfer/homepage/send", False),
    ("https://www.paypal.com/reports/../myaccount/transfer/homepage", False),
    ("https://www.paypal.com/reports/%2e%2e/myaccount/transfer/homepage", False),
    ("https://www.paypal.com/reportsdownload/statement", False),
    ("https://www.paypal.example/reports/apis/download", False),
])
def test_with_no_download_only_an_address_under_reports_is_asked_for_again(
        monkeypatch, tmp_path, href, asked):
    """The page's link is read only for an address it may have saved a
    statement from, under /reports/ on www.paypal.com. Any other address of
    PayPal's own was asked for too (review of c880958)."""
    calls = []
    monkeypatch.setattr(site.blob_capture, "saved_links", lambda page: [href])
    monkeypatch.setattr(site.capture, "ask_again",
                        lambda page, requests, held, safe: calls.append(requests) or False)
    assert site.taken_from_the_page(object(), tmp_path / "statement.pdf") is None
    assert bool(calls) is asked, href
    assert site.is_reports_file(href) is asked
