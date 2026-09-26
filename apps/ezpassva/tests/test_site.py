"""E-ZPass Virginia, the site layer. The guard, the host allowlist, the
period dates, and the statements fragment read from a made-up page. No
real account, no network."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import ezpassva_site as site
from paperpull_core import doc_types


def _row(kind, num, year, label):
    return ('<tr><td>%s</td><td><a class="col text-purple btn-monthly-statement" '
            'href="/Statements/Download?sType=%s&amp;sNum=%d&amp;sYear=%d" '
            'target="_blank">Download</a></td></tr>' % (label, kind, num, year))


# The shape of the real fragment, with invented periods.
FRAGMENT = (
    "<h3>View Online Statements</h3>"
    '<table class="table table-striped table-sm"><tr><th colspan="2">Monthly</th></tr>'
    + _row("1", 2, 2031, "February 2031") + _row("1", 1, 2031, "January 2031")
    + _row("1", 12, 2030, "December 2030") + _row("1", 1, 2031, "January 2031")
    + "</table>"
    '<table class="table table-striped table-sm"><tr><th colspan="2">Quarterly</th></tr>'
    + _row("0", 4, 2030, "Quarter 4, 2030") + _row("0", 3, 2030, "Quarter 3, 2030")
    + "</table>"
    '<a href="https://get.adobe.com/reader/">Adobe Acrobat</a>'
)


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "E-ZPass Virginia"
    assert storage.SPEC.routes["Statement"] == "statements"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


@pytest.mark.parametrize("title,category,summary", [
    ("Monthly Statement - February 2031", "Statement", "Monthly Statement"),
    ("Quarterly Statement - Q4 2030", "Statement", "Quarterly Statement"),
])
def test_the_titles_discovery_writes_classify(title, category, summary):
    rules = doc_types.load_rules()
    got = doc_types.classify_document(title, rules)
    assert (got[0], got[1]) == (category, summary)


def test_a_period_is_dated_by_its_last_day():
    assert site.parse_period_date("Monthly Statement - February 2031") == ("2031-02-28", "February 2031")
    assert site.parse_period_date("Quarterly Statement - Q4 2030")[0] == "2030-12-31"
    assert site.parse_period_date("Quarter 1, 2032")[0] == "2032-03-31"
    assert site.period_end("1", 2, 2032) == "2032-02-29"
    assert site.period_end("0", 2, 2031) == "2031-06-30"
    assert site.parse_date("2031-02-28") == "2031-02-28"
    assert site.parse_date("2031-02-30") is None


def test_the_fragment_is_read_newest_first_once_each():
    got = site.statements_in(FRAGMENT)
    assert [(s["title"], s["date"], s["href"]) for s in got] == [
        ("Monthly Statement - February 2031", "2031-02-28", "/Statements/Download?sType=1&sNum=2&sYear=2031"),
        ("Monthly Statement - January 2031", "2031-01-31", "/Statements/Download?sType=1&sNum=1&sYear=2031"),
        ("Monthly Statement - December 2030", "2030-12-31", "/Statements/Download?sType=1&sNum=12&sYear=2030"),
        ("Quarterly Statement - Q4 2030", "2030-12-31", "/Statements/Download?sType=0&sNum=4&sYear=2030"),
        ("Quarterly Statement - Q3 2030", "2030-09-30", "/Statements/Download?sType=0&sNum=3&sYear=2030"),
    ]
    assert site.looks_like_statements(FRAGMENT)
    assert not site.looks_like_statements("<html>Sign In</html>")


@pytest.mark.parametrize("href", [
    "/Statements/Download?sType=1&sNum=13&sYear=2031",
    "/Statements/Download?sType=0&sNum=5&sYear=2031",
    "/Statements/Download?sType=2&sNum=1&sYear=2031",
    "/Statements/Download?sType=1&sNum=1&sYear=2031&extra=1",
    "/Statements/Delete?sType=1&sNum=1&sYear=2031",
    "https://evil.test/Statements/Download?sType=1&sNum=1&sYear=2031",
])
def test_a_link_that_is_not_exactly_a_statement_is_refused(href):
    assert site.parse_href(href) is None


class _Page:
    """A signed-in portal tab whose fetch answers from a script."""
    url = "https://myaccount.ezpassva.com/"

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, args):
        url, fragment = args
        self.calls.append((url, fragment))
        return self.answers[url]


def _pdf(url):
    return {"status": 200, "ct": "application/pdf;", "url": url,
            "b64": base64.b64encode(b"%PDF-1.4 fake").decode()}


def test_discovery_asks_for_the_fragment_and_keeps_only_the_links():
    page = _Page({site.STATEMENTS_FRAGMENT: {"status": 200, "ct": "text/html",
                                             "url": site.STATEMENTS_FRAGMENT, "text": FRAGMENT}})
    docs = site.collect_download_docs(page)
    assert len(docs) == 5
    assert (docs[0].title, docs[0].date_text, docs[0].account) == \
        ("Monthly Statement - February 2031", "2031-02-28", "")
    assert page.calls == [(site.STATEMENTS_FRAGMENT, True)]


def test_the_download_fetches_the_link_and_writes_only_a_pdf(tmp_path):
    url = site.BASE + "/Statements/Download?sType=0&sNum=4&sYear=2030"
    page = _Page({url: _pdf(url)})
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2030-12-31", out,
                              href="/Statements/Download?sType=0&sNum=4&sYear=2030")
    assert out.read_bytes().startswith(b"%PDF-")
    assert page.calls == [(url, False)]


def test_a_period_the_site_no_longer_lists_is_not_saved(tmp_path):
    """The real site redirects a period it does not list to an error page."""
    url = site.BASE + "/Statements/Download?sType=1&sNum=1&sYear=2031"
    page = _Page({url: {"status": 200, "ct": "text/html; charset=utf-8",
                        "url": site.BASE + "/Home/Error?code=601&PartialV=False",
                        "text": "<!DOCTYPE html>"}})
    out = tmp_path / "s.pdf"
    assert not site.download_bill(page, None, "2031-01-31", out,
                                  href="/Statements/Download?sType=1&sNum=1&sYear=2031")
    assert not out.exists()


def test_a_record_without_a_link_gets_it_back_from_its_title(tmp_path):
    url = site.BASE + "/Statements/Download?sType=1&sNum=12&sYear=2030"
    page = _Page({url: _pdf(url)})
    assert site.download_bill(page, None, "2030-12-31", tmp_path / "s.pdf",
                              title="Monthly Statement - December 2030")
    q = site.BASE + "/Statements/Download?sType=0&sNum=3&sYear=2030"
    page.answers[q] = _pdf(q)
    assert site.download_bill(page, None, "2030-09-30", tmp_path / "q.pdf",
                              title="Quarterly Statement - Q3 2030")


def test_a_link_that_disagrees_with_the_records_date_is_not_fetched(tmp_path):
    page = _Page({})
    assert not site.download_bill(page, None, "2030-11-30", tmp_path / "s.pdf",
                                  href="/Statements/Download?sType=1&sNum=12&sYear=2030")
    assert page.calls == []


def test_a_sign_in_answer_stops_the_run_instead_of_filing_a_failure():
    page = _Page({site.STATEMENTS_FRAGMENT: {"status": 200, "ct": "text/html",
                                             "url": site.BASE + "/Account/Login?ReturnUrl=x",
                                             "text": "<form>Sign In</form>"}})
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)
    page.answers[site.STATEMENTS_FRAGMENT] = {"status": 200, "ct": "text/html",
                                              "url": site.STATEMENTS_FRAGMENT,
                                              "text": "<p>Something else</p>"}
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)
    page.url = "https://myaccount.ezpassva.com/Account/Login"
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)


def test_the_fetch_refuses_any_other_host():
    page = _Page({})
    with pytest.raises(ValueError):
        site._get(page, "https://evil.test/Statements/Online")


def test_moving_money_and_account_controls_are_never_safe():
    for name in ["Make a Payment", "Payments", "Replenish Now", "Change Replenishment Amount",
                 "Add Vehicle", "Vehicles & Transponders", "Order Transponder", "Update Credit Card",
                 "Subscribe to Paper Statements", "Notifications", "Profile", "Close Account",
                 "Pay a Violation", "Log out", "Change password", "Customer Service", "Sign In"]:
        assert not site.is_safe_control(name), name


def test_reading_a_statement_is_safe():
    for name in ["Download", "View Online Statements", "Statements", "Download PDF"]:
        assert site.is_safe_control(name), name


def test_only_ezpassva_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://myaccount.ezpassva.com/Statements/Online")
    assert site.is_safe_url("https://www.ezpassva.com/")
    assert not site.is_safe_url("http://myaccount.ezpassva.com/")
    assert not site.is_safe_url("https://ezpassva.com.example/")
    assert not site.is_safe_url("https://notezpassva.com/")
    assert not site.is_safe_url("https://get.adobe.com/reader/")
    assert not site.is_safe_url("https://user:pw@myaccount.ezpassva.com/")


def test_redaction_masks_long_digit_runs_and_query_strings():
    assert site.redact("account 12345678 at https://myaccount.ezpassva.com/x?tok=abc") == \
        "account ######## at https://myaccount.ezpassva.com/x?..."
