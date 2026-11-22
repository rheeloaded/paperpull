"""How one month's answer is read, and when a statement PDF is taken for
its month. Every value is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fakes  # noqa: E402
from _fakes import FakeTab, body, pdf_answer, statement, status  # noqa: E402
import traderepublic_site as site  # noqa: E402
from paperpull_core import intake  # noqa: E402
from paperpull_core.testkit import sample_pdf, text_pdf  # noqa: E402

MARCH = site.month_of("2026-03")


def ask(answer):
    tab = FakeTab({"2026-03": answer})
    return site.fetch_month(tab, MARCH), tab


# -- one month's answer -------------------------------------------------------

def test_a_pdf_is_a_statement():
    data = statement("2026-03")
    got, tab = ask(pdf_answer(data))
    assert (got.kind, got.data) == (site.PDF, data)
    assert tab.asked == ["2026-03"]


@pytest.mark.parametrize("code", [401, 403])
def test_401_and_403_are_a_sign_out(code):
    assert ask(status(code))[0].kind == site.SIGNED_OUT


def test_429_is_trade_republic_limiting_requests():
    assert ask(status(429))[0].kind == site.LIMITED


@pytest.mark.parametrize("answer", [
    status(404), status(204, ""), status(500), status(302), status(0, ""),
    body(b""),
    body(b"<html><form><input type=password></form>PPCANARYHTML</html>"),
    body(b'{"errors":[{"errorCode":"NOT_FOUND","errorMessage":"PPCANARYJSON"}]}',
         "application/json"),
    body(b"<html>not a pdf</html>", "application/pdf"),
    body(b" %PDF-1.4 leading space", "application/pdf"),
    body(b"\xef\xbb\xbf%PDF-1.4 after a byte order mark", "application/pdf"),
    {"status": "not a number"},
    {},
    None,
], ids=["404", "204", "500", "302", "fetch-failed", "empty-200", "html-200",
        "json-200", "html-as-pdf", "leading-space", "bom", "odd-status", "nothing", "none"])
def test_anything_else_is_a_month_with_no_statement(answer):
    """Never a sign-out and never a statement, whatever the content type."""
    assert ask(answer)[0].kind == site.NO_STATEMENT


def test_the_body_decides_not_the_content_type():
    data = statement("2026-03")
    assert ask(pdf_answer(data, ct="text/html"))[0].kind == site.PDF


def test_a_fetch_the_page_could_not_make_is_no_statement():
    got, _ = ask(RuntimeError("TypeError: Failed to fetch"))
    assert got.kind == site.NO_STATEMENT


def test_a_tab_that_closed_stops_rather_than_counting_a_month():
    tab = FakeTab()

    def close(t):
        t.closed = True
        raise RuntimeError("Target page, context or browser has been closed")
    tab.answers["2026-03"] = close
    with pytest.raises(site.ListStopped):
        site.fetch_month(tab, MARCH)


def test_an_answer_larger_than_a_document_is_not_taken(monkeypatch):
    monkeypatch.setattr(intake, "DOCUMENT_BYTES", 64 * 1024)
    big = b"%PDF-" + b"0" * (64 * 1024)
    assert ask(pdf_answer(big))[0].kind == site.TOO_LARGE


def test_an_address_off_the_api_host_is_never_asked(monkeypatch):
    monkeypatch.setattr(site, "STATEMENT_URL", "https://api.example.test/statement")
    got, tab = ask(pdf_answer(statement("2026-03")))
    assert got.kind == site.NO_STATEMENT and tab.asked == []


def test_the_page_script_checks_the_host_and_refuses_redirects():
    js = site._FETCH_JS
    assert "t.hostname !== 'api.traderepublic.com'" in js
    assert "t.protocol !== 'https:'" in js
    assert "redirect: 'error'" in js and "credentials: 'include'" in js
    assert "WebSocket" not in js and "method" not in js


# -- the session proof ----------------------------------------------------------

def recent():
    return site.months(site.month_of("2026-11").first)[:5]


def test_the_newest_month_answering_proves_a_session():
    tab = FakeTab({"2026-10": pdf_answer(statement("2026-10"))})
    assert site.prove_session(tab, recent())[0] == site.PDF
    assert tab.asked == ["2026-10"]


def test_a_month_with_no_statement_does_not_hide_a_session():
    tab = FakeTab({"2026-10": status(404), "2026-09": pdf_answer(statement("2026-09"))})
    assert site.prove_session(tab, recent())[0] == site.PDF
    assert tab.asked == ["2026-10", "2026-09"]


def test_three_months_with_no_pdf_prove_nothing_and_a_fourth_is_not_asked():
    tab = FakeTab({"2026-10": status(404), "2026-09": status(204, ""),
                   "2026-08": body(b"<html>sign in</html>"),
                   "2026-07": pdf_answer(statement("2026-07"))})
    assert site.prove_session(tab, recent()) == (site.NO_STATEMENT, None)
    assert tab.asked == ["2026-10", "2026-09", "2026-08"]


@pytest.mark.parametrize("code, kind", [(401, site.SIGNED_OUT), (403, site.SIGNED_OUT),
                                        (429, site.LIMITED)])
def test_a_sign_out_or_a_limit_ends_the_proof_at_once(code, kind):
    tab = FakeTab({"2026-10": status(code)})
    assert site.prove_session(tab, recent())[0] == kind
    assert tab.asked == ["2026-10"]


def test_a_sign_out_on_a_later_month_is_still_a_sign_out():
    tab = FakeTab({"2026-10": status(404), "2026-09": status(401)})
    assert site.prove_session(tab, recent())[0] == site.SIGNED_OUT


@pytest.mark.parametrize("url", ["https://app.traderepublic.com/settings",
                                 "https://example.test/boards", "about:blank"])
def test_a_tab_off_the_home_page_is_never_asked(url):
    tab = FakeTab({"2026-10": pdf_answer(statement("2026-10"))}, url=url)
    assert site.prove_session(tab, recent())[0] == site.NO_STATEMENT
    assert tab.asked == []


# -- identity -----------------------------------------------------------------------

def lines(*more):
    return text_pdf(["Invented Broker GmbH", "Kontoauszug fuer einen Monat",
                     "Buchungen und Salden ohne echte Werte", *more])


def test_the_right_month_is_verified():
    check = site.check_period(statement("2026-03"), MARCH)
    assert check.ok and check.days_found == 2


def test_a_neighbors_closing_day_beside_this_months_two_is_still_this_month():
    check = site.check_period(lines("Zeitraum 01.03.2026 - 31.03.2026",
                                    "Anfangssaldo am 28.02.2026"), MARCH)
    assert check.ok


@pytest.mark.parametrize("period", ["2026-02", "2026-04"])
def test_a_neighbors_statement_under_this_months_name_is_refused(period):
    check = site.check_period(statement(period), MARCH)
    assert check.outcome == "refused" and not check.ok


def test_a_pdf_printing_both_months_is_refused():
    check = site.check_period(lines("01.03.2026 - 31.03.2026", "01.04.2026 - 30.04.2026"), MARCH)
    assert check.outcome == "refused"


@pytest.mark.parametrize("text", ["Stichtag 31.03.2026", "Beginn 01.03.2026"])
def test_one_day_of_two_is_not_enough(text):
    check = site.check_period(lines(text), MARCH)
    assert check.outcome == "unchecked" and check.days_found == 1


def test_iso_and_english_forms_are_not_the_named_form():
    check = site.check_period(lines("Zeitraum 2026-03-01 bis 2026-03-31", "March 2026 2026-03"), MARCH)
    assert check.outcome == "unchecked" and check.days_found == 0


def test_month_first_dates_are_never_read_as_german_ones():
    """A January statement with a booking on 03.01.2026, which is March 1st
    written month first, is not March's."""
    jan = lines("Zeitraum 01.01.2026 - 31.01.2026", "Buchung 03.01.2026")
    assert not site.check_period(jan, MARCH).ok


@pytest.mark.parametrize("text", ["Referenz 0103 2026 3103 2026",
                                  "Ref 101.03.20261 und 931.03.20262",
                                  "Ref 01032026 31032026"])
def test_a_day_counts_only_as_a_date_of_its_own(text):
    assert site.check_period(lines(text), MARCH).days_found == 0


def test_a_pdf_with_no_text_is_unreadable():
    assert site.check_period(sample_pdf(), MARCH).outcome == "unreadable"


def test_a_near_empty_text_is_unreadable():
    assert site.check_period(text_pdf(["01.03.2026 31.03.2026"]), MARCH).outcome == "unreadable"


@pytest.mark.parametrize("data", [b"%PDF-", b"%PDF-" + b"\x00junk" * 1000,
                                  statement("2026-03")[:300]])
def test_a_broken_pdf_is_unreadable_and_raises_nothing(data):
    assert site.check_period(data, MARCH).outcome == "unreadable"


def test_february_is_checked_by_its_own_last_day():
    feb24 = site.month_of("2024-02")
    assert site.check_period(lines("01.02.2024 - 29.02.2024"), feb24).ok
    assert not site.check_period(lines("01.02.2024 - 28.02.2024"), feb24).ok
    assert site.check_period(lines("01.02.2025 - 28.02.2025"), site.month_of("2025-02")).ok


def test_rivals_cross_the_year():
    dec = site.month_of("2025-12")
    assert [n.period for n in site.neighbors(dec)] == ["2025-11", "2026-01"]
    assert site.check_period(statement("2025-12"), dec).ok
    assert site.check_period(statement("2026-01"), dec).outcome == "refused"


def test_german_letters_do_not_break_the_reading():
    assert site.check_period(lines("Kontoauszug f\u00fcr M\u00e4rz", "01.03.2026 - 31.03.2026"), MARCH).ok


def test_the_printed_form_is_read_from_its_named_constant(monkeypatch):
    slashed = lines("Zeitraum 01/03/2026 - 31/03/2026")
    assert not site.check_period(slashed, MARCH).ok
    monkeypatch.setattr(site, "PERIOD_DAY_FORM", "%d/%m/%Y")
    assert site.check_period(slashed, MARCH).ok
    assert not site.check_period(statement("2026-03", days=("01.03.2026", "31.03.2026")), MARCH).ok


def test_a_check_reports_names_and_counts_never_a_value():
    report = site.check_period(statement("2026-04"), MARCH).report()
    flat = repr(report)
    for value in ("2026", "03", "31.03", _fakes.CANARY_TEXT, "DE00"):
        assert value not in flat
    assert set(report) == {"outcome", "days_found", "days_expected", "other_month_days_found", "text_chars"}


def test_the_identity_handed_to_delivery_carries_this_months_two_days():
    ident = site.identity_for(MARCH)
    assert ident.extra == ("01.03.2026", "31.03.2026")
    assert not (ident.date or ident.start or ident.period)
    assert [r.extra for r in site.rivals_for(MARCH)] == [("01.02.2026", "28.02.2026"),
                                                        ("01.04.2026", "30.04.2026")]


def test_a_survey_counts_date_shapes_and_holds_no_value():
    data = lines("01.03.2026 - 31.03.2026", "Buchung 15.03.2026", "Export 2026-03-31")
    got = site.survey_pdf(data, MARCH)
    assert got["dates_day_month_year"] == 3 and got["dates_year_month_day"] == 1
    assert got["dates_month_day_year"] == 0
    assert got["first_day_found"] and got["last_day_found"] and got["identity"] == "verified"
    blank = site.survey_pdf(sample_pdf(), MARCH)
    assert blank["text_chars"] == 0 and not blank["first_day_found"] and blank["pages"] == 1
    assert not any(isinstance(v, str) and any(c.isdigit() for c in v) for v in got.values())


# -- the sign-in check --------------------------------------------------------------

class _Dead:
    @property
    def url(self):
        raise RuntimeError("Target page, context or browser has been closed")


def test_a_page_that_cannot_say_where_it_is_is_never_called_signed_in():
    with pytest.raises(RuntimeError):
        site.looks_signed_out(_Dead())


@pytest.mark.parametrize("url, fields, signed_out", [
    ("https://app.traderepublic.com/login", 0, True),
    ("https://app.traderepublic.com/", 1, True),
    ("https://app.traderepublic.com/boards", 1, False),
    ("https://app.traderepublic.com/settings", 0, False),
    ("https://example.test/login", 1, False),
])
def test_a_sign_in_page_is_noticed_and_only_there(url, fields, signed_out):
    assert site.looks_signed_out(FakeTab(url=url, password_fields=fields)) is signed_out
