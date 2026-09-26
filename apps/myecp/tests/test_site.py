"""MILITARY STAR (MyECP), the site layer. The guard, the host allowlist,
the dates, the account links and the statements fragment read from a
made-up page, and the position looked up by date. No real account, no
network."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import myecp_site as site
from paperpull_core import doc_types

SUMMARY = ('<a href="/AccountHome/Index/MILSTAR1?initialview=9">Make Payment</a>'
           '<a href="/AccountHome/Index/MILSTAR1">Manage</a>'
           '<a href="/AccountHome/Index/MILSTAR2?initialview=Statements">Statements</a>')


def _fragment(dates):
    opts = '<option value="">Date</option>' + "".join(
        f'<option value="{i}">{d}</option>' for i, d in enumerate(dates, 1))
    return ('<div id="statementsViewUrl" data-url="/AccountStatement/GetStatement"></div>'
            '<form action="/AccountStatement" method="post">'
            '<input id="AccountIndex" name="AccountIndex" type="hidden" value="MILSTAR1">'
            f'<select id="StatementId" name="StatementId">{opts}</select>'
            '<button id="downloadsatement" type="button">Download as PDF</button></form>')


FRAGMENT = _fragment(["05 Mar 2031", "05 Feb 2031", "05 Jan 2031", "05 Feb 2031", "bad"])


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "MILITARY STAR"
    assert storage.SPEC.routes["Statement"] == "statements"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_the_title_discovery_writes_classifies():
    got = doc_types.classify_document(site.title_for("2031-03-05"), doc_types.load_rules())
    assert (got[0], got[1]) == ("Statement", "Monthly Statement")
    assert site.title_for("2031-03-05") == "Monthly Statement - March 5, 2031"


def test_dates_in_the_shapes_the_site_uses():
    assert site.parse_date("05 Sep 2026") == "2026-09-05"
    assert site.parse_date("5 September 2026") == "2026-09-05"
    assert site.parse_date("2026-09-05") == "2026-09-05"
    assert site.parse_date("31 Feb 2026") is None
    assert site.parse_date("Date") is None


def test_every_card_account_is_found_once_in_order():
    assert site.accounts_in(SUMMARY) == ["MILSTAR1", "MILSTAR2"]
    assert site.accounts_in("<a href='/AccountHome/Index/'>x</a>") == []


def test_the_dropdown_is_read_by_date_with_its_position():
    got = site.statements_in(FRAGMENT)
    assert got == [
        {"position": 1, "date": "2031-03-05", "label": "05 Mar 2031"},
        {"position": 2, "date": "2031-02-05", "label": "05 Feb 2031"},
        {"position": 3, "date": "2031-01-05", "label": "05 Jan 2031"},
    ]
    assert site.looks_like_statements(FRAGMENT)
    assert not site.looks_like_statements("<html>Log in</html>")
    assert site.view_url_in(FRAGMENT) == "/AccountStatement/GetStatement"
    assert site.view_url_in("") == site.GET_STATEMENT


def test_the_download_address_is_the_one_the_page_script_builds():
    assert site.statement_url("/AccountStatement/GetStatement", 2, "MILSTAR1") == \
        "https://www.myecp.com/AccountStatement/GetStatement/2?downloadstatement=true&AccountIndex=MILSTAR1"


class _Page:
    """A signed-in MyECP tab on the Account Summary whose fetch answers
    from a script."""
    url = "https://www.myecp.com/AccountSummary"

    def __init__(self, answers, summary=SUMMARY):
        self.answers, self.summary = answers, summary
        self.calls = []

    def content(self):
        return self.summary

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, args):
        url, fragment = args
        self.calls.append(url)
        return self.answers[url]


def _frag_answer(acct, html):
    url = site.fragment_url(acct)
    return url, {"status": 200, "ct": "text/html", "url": url, "text": html}


def test_discovery_reads_every_account_and_labels_them_when_there_are_several():
    u1, a1 = _frag_answer("MILSTAR1", FRAGMENT)
    u2, a2 = _frag_answer("MILSTAR2", _fragment(["05 Mar 2031"]))
    docs = site.collect_download_docs(_Page({u1: a1, u2: a2}))
    assert [(d.date_text, d.account, d.href) for d in docs] == [
        ("2031-03-05", "MILSTAR1", "MILSTAR1"), ("2031-02-05", "MILSTAR1", "MILSTAR1"),
        ("2031-01-05", "MILSTAR1", "MILSTAR1"), ("2031-03-05", "MILSTAR2", "MILSTAR2")]


def test_one_account_leaves_the_label_empty():
    u1, a1 = _frag_answer("MILSTAR1", FRAGMENT)
    page = _Page({u1: a1}, summary='<a href="/AccountHome/Index/MILSTAR1">x</a>')
    assert {d.account for d in site.collect_download_docs(page)} == {""}


def test_the_download_looks_up_todays_position_for_the_date(tmp_path):
    """A month later the same statement sits one place lower."""
    u1, a1 = _frag_answer("MILSTAR1", _fragment(["05 Apr 2031", "05 Mar 2031", "05 Feb 2031"]))
    pdf_url = site.statement_url("/AccountStatement/GetStatement", 3, "MILSTAR1")
    page = _Page({u1: a1, pdf_url: {"status": 200, "ct": "application/pdf", "url": pdf_url,
                                    "b64": base64.b64encode(b"%PDF-1.6 fake").decode()}})
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2031-02-05", out, href="MILSTAR1")
    assert out.read_bytes().startswith(b"%PDF-")
    assert page.calls[-1] == pdf_url


def test_a_statement_no_longer_listed_or_not_a_pdf_is_not_saved(tmp_path):
    u1, a1 = _frag_answer("MILSTAR1", FRAGMENT)
    pdf_url = site.statement_url("/AccountStatement/GetStatement", 1, "MILSTAR1")
    page = _Page({u1: a1, pdf_url: {"status": 200, "ct": "text/html", "url": pdf_url, "text": "<html>"}})
    assert not site.download_bill(page, None, "2020-01-05", tmp_path / "a.pdf", href="MILSTAR1")
    assert not site.download_bill(page, None, "2031-03-05", tmp_path / "b.pdf", href="MILSTAR1")
    assert not (tmp_path / "b.pdf").exists()


def test_an_account_index_that_is_not_one_is_not_used(tmp_path):
    u1, a1 = _frag_answer("MILSTAR1", FRAGMENT)
    page = _Page({u1: a1}, summary='<a href="/AccountHome/Index/MILSTAR1">x</a>')
    pdf_url = site.statement_url("/AccountStatement/GetStatement", 1, "MILSTAR1")
    page.answers[pdf_url] = {"status": 200, "ct": "application/pdf", "url": pdf_url,
                             "b64": base64.b64encode(b"%PDF-1.6 fake").decode()}
    assert site.download_bill(page, None, "2031-03-05", tmp_path / "s.pdf", href="../../evil")
    assert page.calls[-1] == pdf_url


def test_a_sign_in_answer_stops_the_run():
    url = site.fragment_url("MILSTAR1")
    page = _Page({url: {"status": 200, "ct": "text/html", "url": site.BASE + "/Account/Login?ReturnUrl=x",
                        "text": "<form>Log in</form>"}})
    with pytest.raises(site.SessionExpired):
        site.list_statements(page, "MILSTAR1")
    page.answers[url] = {"status": 200, "ct": "text/html", "url": url, "text": "<p>Something else</p>"}
    with pytest.raises(site.SessionExpired):
        site.list_statements(page, "MILSTAR1")


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._get(_Page({}), "https://evil.test/AccountStatement/GetStatement/1")


def test_money_and_account_controls_are_never_safe():
    for name in ["Make Payment", "Payments", "Manage Account", "View Points", "Rewards Activity",
                 "Promotions", "Products", "Apply for a card", "Add Authorized User",
                 "Log Out", "Contact Us", "Payment History"]:
        assert not site.is_safe_control(name), name


def test_reading_a_statement_is_safe():
    for name in ["Statements", "Download as PDF", "View PDF Now"]:
        assert site.is_safe_control(name), name


def test_only_myecp_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.myecp.com/AccountSummary")
    assert not site.is_safe_url("http://www.myecp.com/")
    assert not site.is_safe_url("https://myecp.com.example/")
    assert not site.is_safe_url("https://notmyecp.com/")
    assert not site.is_safe_url("https://www.mcafeesecure.com/RatingVerify")
    assert not site.is_safe_url("https://user:pw@www.myecp.com/")
