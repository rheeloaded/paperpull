"""Poppins Payroll: the guards that matter on a payroll site, and the three
lists read from pages shaped like Poppins' own. Every name, amount and id
here is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  (binds the AppSpec)
import poppins_site as site

B = "https://app.poppinspayroll.com"


# --- the address guard -----------------------------------------------------

@pytest.mark.parametrize("url", [
    B + "/v2/payroll",
    B + "/v2/payroll?year=2026",
    B + "/v2/payroll?year=2025&page=3",
    B + "/v2/payroll/1234567/paystub",
    B + "/v2/documents?tab=employer",
    B + "/v2/documents?tab=employee&year=2025",
    B + "/v2/documents/7654321",
    B + "/v2/documents/overtime-report/11111/2025",
    B + "/accounts/storage/22222/er22222.schedule_h.20251231.pdf",
    B + "/v2/taxes/federal",
    B + "/v2/taxes/state",
])
def test_the_lists_and_documents_are_allowed(url):
    assert site.is_safe_url(url), url


@pytest.mark.parametrize("url", [
    # A payroll's own page is the form that edits hours and pay.
    B + "/v2/payroll/1234567",
    B + "/v2/payroll/1234567/edit",
    B + "/v2/settings",
    B + "/v2/settings?tab=time-tracking",
    B + "/v2/employees",
    B + "/v2/documents/fsa-receipt?back=documents",
    B + "/referrals/employer-referral-invitation",
    B + "/logout",
    B + "/v2/payroll?year=2026&run=1",
    "http://app.poppinspayroll.com/v2/payroll",
    "https://app.poppinspayroll.com.example.test/v2/payroll",
    "https://app.poppinspayroll.com@example.test/v2/payroll",
    "https://www.poppinspayroll.com/v2/payroll",
    "https://example.test/accounts/storage/1/x.pdf",
])
def test_everything_else_is_refused(url):
    assert not site.is_safe_url(url), url


@pytest.mark.parametrize("label", ["Download", "Download pay stub", "W-2", "Schedule H"])
def test_document_controls_are_allowed(label):
    assert site.is_safe_control(label)


@pytest.mark.parametrize("label", [
    "Edit payroll", "Edit", "Run payroll", "Approve hours", "Submit",
    "Generate", "Generate FSA receipt", "Set up time tracking",
    "Change bank account", "Update direct deposit", "Sign out", "Log out now",
    "Save", "Delete", "Refer & Earn", "Download and approve",
])
def test_controls_that_change_anything_are_refused(label):
    assert not site.is_safe_control(label)


def test_a_word_ending_in_edit_is_not_refused_for_it():
    assert not site.FORBIDDEN_CONTROL_RE.search("Tax credit")
    assert not site.FORBIDDEN_CONTROL_RE.search("Credited")


# --- payroll ----------------------------------------------------------------

def _payroll_row(name, period, pay_day, status, action_href, action_label):
    return f"""
    <tr class="pp-table__row">
      <td class="pp-table__cell" data-label="Employee and pay period">
        <div class="pp-table__employee"><span aria-hidden="true">{name[0]}</span>
          <div class="pp-table__employee-detail">
            <p class="pp-table__cell--title">{name}</p>
            <p class="pp-table__cell--description">{period}</p></div></div></td>
      <td class="pp-table__cell" data-label="Pay day"> {pay_day} </td>
      <td class="pp-table__cell" data-label="Gross amount"> $500.00 </td>
      <td class="pp-table__cell" data-label="Net pay"> $400.00 </td>
      <td class="pp-table__cell" data-label="Status"><div>
        <span class="pp-confirmation-badge__label"> {status} </span></div></td>
      <td class="pp-table__cell" data-label="Actions"><div class="pp-table__action">
        <a role="button" href="{action_href}"><span class="pp-btn__label">{action_label}</span>
        <svg><path d="M1 2"/></svg></a></div></td>
    </tr>"""


def _payroll_page(rows, next_href=""):
    table = f"<table><tr class='pp-table__header-row'><th>Pay day</th></tr>{rows}</table>"
    nxt = f'<a class="pp-pagination__btn" href="{next_href}" rel="next" aria-label="Next page"></a>' \
        if next_href else ""
    return f"""<html><body><script>var x = "<tr class='pp-table__row'>";</script>
      <a href="?year=2026" role="menuitem"> 2026 </a><a href="?year=2025" role="menuitem"> 2025 </a>
      {table}{table}{nxt}</body></html>"""


PAYROLL = _payroll_page(
    _payroll_row("Alex Sample", "March 7-13, 2026", "Mar 20, 2026", "Open",
                 "/v2/payroll/1000003", "Edit payroll")
    + _payroll_row("Alex Sample", "February 28-March 6, 2026", "Mar 13, 2026", "Complete",
                   "/v2/payroll/1000002/paystub", "Download")
    + _payroll_row("Alex Sample", "February 21-27, 2026", "Mar 6, 2026", "Complete",
                   "/v2/payroll/1000001/paystub", "Download"),
    next_href="?year=2026&amp;page=2")


def test_only_complete_payrolls_with_a_stub_are_listed():
    docs = site.paystubs_of(site.read_html(PAYROLL))
    ids = [d.document_id for d in docs]
    # The page draws the table twice; the collector keeps each once.
    assert sorted(set(ids)) == ["paystub-1000001", "paystub-1000002"]
    d = next(d for d in docs if d.document_id == "paystub-1000002")
    assert d.date_text == "2026-03-13"
    assert d.href == "/v2/payroll/1000002/paystub"
    assert d.account == "Alex Sample"
    assert d.title == "Pay Stub February 28-March 6, 2026"
    assert d.kind == site.PAYSTUB


def test_the_open_payroll_is_never_listed():
    docs = site.paystubs_of(site.read_html(PAYROLL))
    assert all("1000003" not in d.document_id for d in docs)
    assert all(d.href.endswith("/paystub") for d in docs)


def test_years_and_next_page():
    read = site.read_html(PAYROLL)
    assert site.years_of(read) == ["2026", "2025"]
    assert site.older_page_link(read) == "?year=2026&page=2"
    assert site.older_page_link(site.read_html(_payroll_page(""))) == ""


def test_a_stub_row_without_a_readable_pay_day_stops_the_list():
    page = _payroll_page(_payroll_row("Alex Sample", "March 7-13, 2026", "soon", "Complete",
                                      "/v2/payroll/1000009/paystub", "Download"))
    with pytest.raises(site.ListStopped):
        site.paystubs_of(site.read_html(page))


# --- documents --------------------------------------------------------------

def _doc_row(name, year, made, href, employee=""):
    emp = f'<span class="typography-body-sm pp-avatar-label__secondary">{employee}</span>' \
        if employee else ""
    return f"""
    <tr class="pp-table__row">
      <td class="pp-table__cell" data-label="Document"><div class="pp-avatar-label">
        <span class="pp-avatar-label__meta">
        <span class="typography-body-sm pp-avatar-label__primary">{name}</span>{emp}</span></div></td>
      <td class="pp-table__cell" data-label="Year"> {year} </td>
      <td class="pp-table__cell" data-label="Category"> Federal tax </td>
      <td class="pp-table__cell" data-label="Description"><span>About {name}.</span></td>
      <td class="pp-table__cell" data-label="Status"> {made} </td>
      <td class="pp-table__cell"><a target="_blank" role="button" href="{href}">
        <span class="pp-btn__label">Download</span></a></td>
    </tr>"""


DOCUMENTS = "<table>" + "".join([
    _doc_row("Schedule H", "2025", "Created Jan 21, 2026", "/v2/documents/500003"),
    _doc_row("Form SS4", "2025", "Created Sep 9, 2025", "/v2/documents/500001"),
    _doc_row("W-2", "2025", "Created Jan 12, 2026", "/v2/documents/500002", "Alex Sample"),
    _doc_row("Overtime premium report", "2025", "", "/v2/documents/overtime-report/33333/2025",
             "Alex Sample"),
]) + "</table>"


def test_forms_are_listed_with_their_year_and_employee():
    docs = {d.document_id: d for d in site.forms_of(site.read_html(DOCUMENTS))}
    assert set(docs) == {"form-500003", "form-500001", "form-500002", "overtime-33333-2025"}
    assert docs["form-500002"].title == "W-2 2025"
    assert docs["form-500002"].account == "Alex Sample"
    assert docs["overtime-33333-2025"].href == "/v2/documents/overtime-report/33333/2025"


def test_annual_forms_are_dated_at_year_end_and_setup_forms_when_made():
    docs = {d.document_id: d for d in site.forms_of(site.read_html(DOCUMENTS))}
    assert docs["form-500003"].date_text == "2025-12-31"     # Schedule H
    assert docs["form-500002"].date_text == "2025-12-31"     # W-2
    assert docs["overtime-33333-2025"].date_text == "2025-12-31"
    assert docs["form-500001"].date_text == "2025-09-09"     # SS-4, the day it was made


# --- tax payment history ----------------------------------------------------

def _tax_page(rows):
    wide = "".join(f"""<tr class="pp-table__row">
      <td class="pp-table__cell" data-label="Period / Year"> {p} </td>
      <td class="pp-table__cell" data-label="Type"> {t} </td>
      <td class="pp-table__cell" data-label="Date"> {d} </td>
      <td class="pp-table__cell" data-label="Amount"> {a} </td>
      <td class="pp-table__cell" data-label="Status"><div><span> Successfully withdrawn </span></div></td>
      </tr>""" for p, t, d, a in rows)
    narrow = "".join(f"""<tr class="pp-table__row">
      <td class="pp-table__cell" data-label="Period / Year"> {p} {t} {d} </td>
      <td class="pp-table__cell" data-label="Amount"> {a} </td>
      <td class="pp-table__cell" data-label="Status"> Successfully withdrawn </td></tr>"""
                     for p, t, d, a in rows)
    summary = """<table><tr class="pp-table__row"><td data-label="Tax type">Medicare Tax</td>
      <td data-label="Total">$1.00</td></tr></table>"""
    return f"""<html><body>{summary}<section id="payment-history"><h2>Payment History</h2>
      <table>{wide}</table><table>{narrow}</table></section></body></html>"""


FEDERAL = _tax_page([("Q2 2026", "Federal tax", "June 17, 2026", "$100.00"),
                     ("Q1 2026", "Federal tax", "April 14, 2026", "$90.00")])


def test_payments_are_read_once_from_the_wide_table():
    pays = site.payments_of(site.read_html(FEDERAL))
    assert [(p.period, p.day, p.amount) for p in pays] == [
        ("Q2 2026", "2026-06-17", "$100.00"), ("Q1 2026", "2026-04-14", "$90.00")]


def test_a_payment_history_is_known_by_its_newest_payment_and_count():
    doc = site.payments_doc("federal", site.payments_of(site.read_html(FEDERAL)))
    assert doc.document_id == "federal-payments-2026-06-17-2"
    assert doc.date_text == "2026-06-17"
    assert doc.title == "Federal Tax Payment History 2026-06-17"
    assert doc.href == "/v2/taxes/federal"
    more = _tax_page([("Q3 2026", "Federal tax", "September 22, 2026", "$110.00"),
                      ("Q2 2026", "Federal tax", "June 17, 2026", "$100.00"),
                      ("Q1 2026", "Federal tax", "April 14, 2026", "$90.00")])
    newer = site.payments_doc("federal", site.payments_of(site.read_html(more)))
    assert newer.document_id != doc.document_id
    assert site.payments_doc("state", []) is None


def test_the_payment_history_page_escapes_what_it_shows():
    html = site.payments_html("Federal Tax Payment History", [
        site.Payment("Q1 2026", "<b>Federal</b>", "2026-04-14", "$1.00", "ok")], "2026-04-15")
    assert "<b>Federal</b>" not in html
    assert "&lt;b&gt;Federal&lt;/b&gt;" in html
    assert "transcribed from app.poppinspayroll.com on 2026-04-15" in html


def test_a_sign_in_page_is_noticed():
    read = site.read_html("<form><input type='email'><input type='password'></form>")
    assert read.has_password_field


@pytest.mark.parametrize("text,iso", [
    ("Nov 27, 2026", "2026-11-27"), ("September 22, 2026", "2026-09-22"),
    ("Created Jan 21, 2026", "2026-01-21"), ("soon", ""), ("Feb 30, 2026", ""),
])
def test_dates(text, iso):
    assert site.parse_day(text) == iso
