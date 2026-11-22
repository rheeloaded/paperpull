"""The page script in a real Chromium, against an invented Trade Republic.

Nothing here reaches a network. Every host resolves to nothing, and a
router answers only the web app's home page and the statement route, and
records everything it is asked. A fulfilled answer is not held to CORS here,
so whether the API lets the web app read it is for a tester to show. The statement route answers 401 unless the
invented session cookie arrives, so a statement that answers proves the
script sent the tab's cookies across to the API host. Every value is
invented."""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fakes import READY, statement  # noqa: E402
import traderepublic_site as site  # noqa: E402

COOKIE = "PPCANARYCOOKIE41"
ORIGIN = "https://app.traderepublic.com"
REDIRECTED = "https://api.traderepublic.com/redirected.pdf"


@pytest.fixture
def web():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND",
                                                   "--no-proxy-server"])
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        context = browser.new_context(service_workers="block")
        context.add_cookies([{"name": "trsess", "value": COOKIE,
                              "domain": "api.traderepublic.com", "path": "/",
                              "secure": True, "sameSite": "Lax"}])
        seen, off_route = [], []
        plan = {}

        def route(mock):
            request = mock.request
            parts = urlsplit(request.url)
            seen.append((request.method, parts.hostname, parts.path))
            if request.url == READY:
                return mock.fulfill(content_type="text/html",
                                    body="<title>Trade Republic</title><main>Boards</main>")
            if parts.hostname == "api.traderepublic.com" and parts.path == urlsplit(site.STATEMENT_URL).path:
                period = parse_qs(parts.query)["fromDate"][0][:7]
                cors = {"Access-Control-Allow-Origin": ORIGIN,
                        "Access-Control-Allow-Credentials": "true"}
                how = plan.get(period, "pdf")
                if COOKIE not in request.all_headers().get("cookie", ""):
                    return mock.fulfill(status=401, headers=cors, body="")
                if how == "redirect":
                    return mock.fulfill(status=302, headers={**cors, "Location": REDIRECTED}, body="")
                if how == "404":
                    return mock.fulfill(status=404, headers=cors, body="")
                return mock.fulfill(status=200, headers=cors, content_type="application/pdf",
                                    body=statement(period))
            off_route.append(request.url)
            return mock.abort()

        context.route("**/*", route)
        page = context.new_page()
        page.goto(READY)
        yield page, plan, seen, off_route, context
        browser.close()


def test_a_statement_comes_back_whole_with_the_tabs_cookie(web):
    page, plan, seen, off_route, _ = web
    m = site.month_of("2026-03")
    got = site.fetch_month(page, m)
    assert got.kind == site.PDF and got.data == statement("2026-03")
    assert site.check_period(got.data, m).ok
    assert seen == [("GET", "app.traderepublic.com", "/boards"),
                    ("GET", "api.traderepublic.com", urlsplit(site.STATEMENT_URL).path)]
    assert off_route == [] and page.url == READY


def test_without_the_cookie_it_is_a_sign_out(web):
    page, plan, seen, off_route, context = web
    context.clear_cookies()
    assert site.fetch_month(page, site.month_of("2026-03")).kind == site.SIGNED_OUT


def test_a_redirect_is_never_followed(web):
    page, plan, seen, off_route, _ = web
    plan["2026-03"] = "redirect"
    assert site.fetch_month(page, site.month_of("2026-03")).kind == site.NO_STATEMENT
    assert not any(path == "/redirected.pdf" for _, _, path in seen)
    assert off_route == []


def test_a_month_answered_404_is_no_statement(web):
    page, plan, *_ = web
    plan["2026-03"] = "404"
    assert site.fetch_month(page, site.month_of("2026-03")).kind == site.NO_STATEMENT


@pytest.mark.parametrize("url", ["https://example.test/statement",
                                 "http://api.traderepublic.com/statement",
                                 "https://app.traderepublic.com/statement"])
def test_the_page_script_refuses_any_other_address_before_asking(web, url):
    page, plan, seen, off_route, _ = web
    before = len(seen)
    with pytest.raises(Exception, match="Refusing an off-host request"):
        page.evaluate(site.intake.reading(site._FETCH_JS), {"url": url})
    assert len(seen) == before and off_route == []
