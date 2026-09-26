"""PayPal, the site layer. The guard, the host allowlist, the month keys,
and the list answer read from a made-up body. No real account, no
network."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # binds this provider's AppSpec
import paypal_site as site
from paperpull_core import doc_types


def _month(key, name):
    return {"month": name, "date": key, "title": name, "monthNumber": int(key[4:6]), "year": key[:4]}


# The shape of the real answer, with invented months.
ANSWER = {"data": {"statements": [
    {"year": "2031", "details": [_month("20310201", "February"), _month("20310101", "January")]},
    {"year": "2030", "details": [_month("20301201", "December"), _month("20301201", "December"),
                                 _month("2030-11", "bad"), _month("20301301", "bad"),
                                 _month("20301115", "not the first")]},
]}, "sys": {"pageInfo": {}}}


def test_the_folders_and_categories_are_what_the_index_expects():
    assert storage.SPEC.provider == "PayPal"
    assert storage.SPEC.routes["Statement"] == "statements"
    assert storage.SPEC.config_defaults["document_types"] == ["Statement"]


def test_the_title_discovery_writes_classifies():
    got = doc_types.classify_document("Monthly Statement - February 2031", doc_types.load_rules())
    assert (got[0], got[1]) == ("Statement", "Monthly Statement")


def test_a_month_key_is_read_strictly():
    assert site.month_of("20310201") == (2031, 2)
    for bad in ["2031-02", "20311301", "20310215", "19990101", "", "2031020"]:
        assert site.month_of(bad) is None, bad
    assert site.month_end(2032, 2) == "2032-02-29"
    assert site.key_for("Monthly Statement - February 2031") == "20310201"
    assert site.parse_period_date("Monthly Statement - February 2031")[0] == "2031-02-28"


def test_the_list_is_read_newest_first_once_each():
    got = site.statements_in(ANSWER)
    assert [(s["title"], s["date"], s["href"]) for s in got] == [
        ("Monthly Statement - February 2031", "2031-02-28",
         "/myaccount/statements/api/statements/download?monthList=20310201&reportType=standard"),
        ("Monthly Statement - January 2031", "2031-01-31",
         "/myaccount/statements/api/statements/download?monthList=20310101&reportType=standard"),
        ("Monthly Statement - December 2030", "2030-12-31",
         "/myaccount/statements/api/statements/download?monthList=20301201&reportType=standard"),
    ]
    assert site.statements_in({}) == []


@pytest.mark.parametrize("href", [
    "/myaccount/statements/api/statements/download?monthList=20310201,20310101&reportType=standard",
    "/myaccount/statements/api/statements/download?monthList=20310201&reportType=savings",
    "/myaccount/statements/api/statements/download?monthList=20311301&reportType=standard",
    "https://evil.test/myaccount/statements/api/statements/download?monthList=20310201&reportType=standard",
    "/myaccount/transfer?monthList=20310201&reportType=standard",
])
def test_a_link_that_is_not_exactly_one_statement_is_refused(href):
    assert site.parse_href(href) == ""


class _Page:
    """A signed-in PayPal tab whose fetch answers from a script."""
    url = "https://www.paypal.com/myaccount/statements/monthly"

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def locator(self, *_):
        class _L:
            def count(self): return 0
        return _L()

    def evaluate(self, _js, url):
        self.calls.append(url)
        return self.answers[url]


def test_discovery_asks_the_list_endpoint():
    page = _Page({site.LIST_API: {"status": 200, "ct": "application/json", "url": site.LIST_API,
                                  "json": ANSWER}})
    docs = site.collect_download_docs(page)
    assert [(d.title, d.date_text, d.account) for d in docs][0] == \
        ("Monthly Statement - February 2031", "2031-02-28", "")
    assert page.calls == [site.LIST_API]


def test_the_download_fetches_the_month_and_writes_only_a_pdf(tmp_path):
    url = site.BASE + site.download_href("20310101")
    page = _Page({url: {"status": 200, "ct": "application/pdf", "url": url,
                        "b64": base64.b64encode(b"%PDF-1.4 fake").decode()}})
    out = tmp_path / "s.pdf"
    assert site.download_bill(page, None, "2031-01-31", out, href=site.download_href("20310101"))
    assert out.read_bytes().startswith(b"%PDF-")
    page.answers[url] = {"status": 200, "ct": "text/html", "url": url}
    out2 = tmp_path / "t.pdf"
    assert not site.download_bill(page, None, "2031-01-31", out2, href=site.download_href("20310101"))
    assert not out2.exists()


def test_a_record_without_a_link_gets_it_back_from_its_title(tmp_path):
    url = site.BASE + site.download_href("20301201")
    page = _Page({url: {"status": 200, "ct": "application/pdf", "url": url,
                        "b64": base64.b64encode(b"%PDF-1.4 fake").decode()}})
    assert site.download_bill(page, None, "2030-12-31", tmp_path / "s.pdf",
                              title="Monthly Statement - December 2030")


def test_a_link_that_disagrees_with_the_records_date_is_not_fetched(tmp_path):
    page = _Page({})
    assert not site.download_bill(page, None, "2030-11-30", tmp_path / "s.pdf",
                                  href=site.download_href("20301201"))
    assert page.calls == []


def test_a_sign_in_answer_stops_the_run_instead_of_filing_a_failure():
    page = _Page({site.LIST_API: {"status": 200, "ct": "text/html",
                                  "url": "https://www.paypal.com/signin?returnUri=x"}})
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)
    page.answers[site.LIST_API] = {"status": 200, "ct": "text/html", "url": site.LIST_API}
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)
    page.url = "https://www.paypal.com/signin"
    with pytest.raises(site.SessionExpired):
        site.list_statements(page)


def test_the_fetch_refuses_any_other_host():
    with pytest.raises(ValueError):
        site._get(_Page({}), "https://evil.test/myaccount/statements/api/statements")


def test_moving_money_and_account_controls_are_never_safe():
    for name in ["Send and Request", "Send again", "Transfer Money", "Donate", "Reload phone",
                 "Buy, sell or hold crypto.", "Start Saving", "Save Offer", "Learn More",
                 "Apply for the PayPal Cashback Mastercard", "Custom Request a statement",
                 "File taxes", "Settings", "LOG OUT", "Security", "Notifications", "dismiss"]:
        assert not site.is_safe_control(name), name


def test_reading_a_statement_is_safe():
    for name in ["Download", "Download all", "All transactions", "Statements"]:
        assert site.is_safe_control(name), name


def test_only_paypal_com_and_its_subdomains_are_allowed():
    assert site.is_safe_url("https://www.paypal.com/myaccount/statements/monthly")
    assert not site.is_safe_url("http://www.paypal.com/")
    assert not site.is_safe_url("https://paypal.com.example/")
    assert not site.is_safe_url("https://notpaypal.com/")
    assert not site.is_safe_url("https://www.paypalobjects.com/x.js")
    assert not site.is_safe_url("https://user:pw@www.paypal.com/")
