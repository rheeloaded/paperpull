"""Which months are asked, how they are written, and which tabs and hosts
the app will use. Every value is invented."""
from datetime import date
from urllib.parse import parse_qs, urlsplit

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fakes  # noqa: F401  puts the app on the path
import traderepublic_site as site


def periods(on):
    return [m.period for m in site.months(on)]


def test_the_window_is_the_complete_months_of_the_last_1100_days():
    got = site.months(date(2026, 11, 20))
    assert len(got) == 36
    assert got[0].period == "2026-10" and got[-1].period == "2023-11"
    assert "2026-11" not in [m.period for m in got]
    by = {m.period: m for m in got}
    assert by["2026-10"].date == "2026-10-31"
    assert by["2024-02"].date == "2024-02-29"
    assert by["2023-11"].date == "2023-11-30"


@pytest.mark.parametrize("on, newest, oldest, count", [
    (date(2026, 11, 1), "2026-10", "2023-10", 37),
    (date(2026, 10, 31), "2026-09", "2023-10", 36),
    (date(2026, 11, 4), "2026-10", "2023-10", 37),
    (date(2026, 11, 5), "2026-10", "2023-11", 36),
    (date(2026, 12, 4), "2026-11", "2023-11", 37),
    (date(2026, 12, 5), "2026-11", "2023-12", 36),
    (date(2027, 1, 1), "2026-12", "2023-12", 37),
    (date(2026, 12, 31), "2026-11", "2023-12", 36),
    (date(2024, 3, 1), "2024-02", "2021-02", 37),
    (date(2024, 2, 29), "2024-01", "2021-02", 36),
])
def test_the_window_at_its_edges(on, newest, oldest, count):
    got = periods(on)
    assert (got[0], got[-1], len(got)) == (newest, oldest, count)


def test_months_are_newest_first_and_each_one_once():
    got = periods(date(2027, 1, 3))
    assert got == sorted(got, reverse=True) and len(set(got)) == len(got)
    assert got[:3] == ["2026-12", "2026-11", "2026-10"]


@pytest.mark.parametrize("period, to", [
    ("2026-01", "2026-01-31"), ("2026-02", "2026-02-28"), ("2024-02", "2024-02-29"),
    ("2026-04", "2026-04-30"), ("2026-06", "2026-06-30"), ("2026-12", "2026-12-31"),
])
def test_a_months_request_names_its_first_and_last_day(period, to):
    url = site.statement_url(site.month_of(period))
    parts = urlsplit(url)
    assert (parts.scheme, parts.hostname, parts.path) == (
        "https", "api.traderepublic.com",
        "/api/v1/banking/consumer/accountstatement/statement")
    assert parse_qs(parts.query) == {"fromDate": [period + "-01"], "toDate": [to]}


def test_the_request_form_is_read_from_its_named_constant(monkeypatch):
    monkeypatch.setattr(site, "DATE_PARAM_FORM", "%d.%m.%Y")
    query = parse_qs(urlsplit(site.statement_url(site.month_of("2026-03"))).query)
    assert query == {"fromDate": ["01.03.2026"], "toDate": ["31.03.2026"]}


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "2026-3", "march", ""])
def test_a_period_that_is_not_a_month_is_none(bad):
    assert site.month_of(bad) is None


@pytest.mark.parametrize("url", [
    "https://app.traderepublic.com/boards",
    "https://api.traderepublic.com/api/v1/banking/consumer/accountstatement/statement?fromDate=2026-10-01&toDate=2026-10-31",
])
def test_the_two_hosts_are_allowed(url):
    assert site.is_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://app.traderepublic.com/boards", "http://api.traderepublic.com/x",
    "wss://api.traderepublic.com/", "https://traderepublic.com/",
    "https://www.traderepublic.com/", "https://x.app.traderepublic.com/",
    "https://app.traderepublic.com.example.test/", "https://example.test/?u=app.traderepublic.com",
    "https://app.traderepublic.com@example.test/", "https://example.test\\@api.traderepublic.com/",
    "https://api.traderepublic.com:notaport/",
])
def test_every_other_address_is_refused(url):
    assert not site.is_safe_url(url)
    assert not site.is_ready_url(url)


@pytest.mark.parametrize("url", [
    "https://app.traderepublic.com/boards", "https://app.traderepublic.com/boards/",
    "https://app.traderepublic.com/boards/portfolio/overview",
    "https://app.traderepublic.com/boards?tab=1#cash",
])
def test_the_home_page_and_pages_under_it_are_ready(url):
    assert site.is_ready_url(url)


@pytest.mark.parametrize("url", [
    "https://app.traderepublic.com/boardsx", "https://app.traderepublic.com/board",
    "https://app.traderepublic.com/", "https://app.traderepublic.com/login",
    "https://app.traderepublic.com/settings/boards", "http://app.traderepublic.com/boards",
    "https://api.traderepublic.com/boards", "https://example.test/boards",
    "https://traderepublic.com/de-de", "about:blank", "",
])
def test_no_other_page_is_ready(url):
    assert not site.is_ready_url(url)


def test_the_api_host_is_not_a_page_of_the_web_app():
    assert not site.is_app_url("https://api.traderepublic.com/boards")
    assert site.is_app_url("https://app.traderepublic.com/settings")


@pytest.mark.parametrize("label", [
    "Kaufen", "Verkaufen", "Buy", "Sell", "Transfer", "Sparplan erstellen",
    "Change PIN", "Sign out", "Delete account", "Confirm order",
])
def test_trading_and_account_controls_are_refused(label):
    assert not site.is_safe_control(label)
