"""The page's own fetch, run in a real browser against a routed, offline
Raisin dashboard and API. Every name resolves to nothing, so nothing can
leave this computer, and every request the page makes is seen here.

What only a browser can prove: the request is a GET with the bearer token
from localStorage and no cookie, a redirect is never followed, and the
token never comes back to Python.
"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import raisin_site as site
from fake_raisin import CUSTOMER, DASHBOARD, TOKEN, pdf_for
from paperpull_core import intake

PAGE_URL = DASHBOARD % CUSTOMER
PDF = pdf_for("05.03.2026", "Kontoauszug")
CORS = {"Access-Control-Allow-Origin": "https://www.raisin.com",
        "Access-Control-Allow-Headers": "authorization, accept",
        "Access-Control-Allow-Methods": "GET"}


@pytest.fixture
def dashboard():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND",
                                                   "--no-proxy-server"])
        except pw.Error as exc:
            pytest.skip(f"no browser to drive: {exc}")
        context = browser.new_context(service_workers="block")
        # A cookie the API host would get if the fetch sent cookies.
        context.add_cookies([{"name": "session", "value": "cookie-canary",
                              "domain": "api2.weltsparen.de", "path": "/",
                              "secure": True, "sameSite": "None"}])
        seen, answers = [], {}

        def route(mock):
            request = mock.request
            seen.append((request.method, request.url, dict(request.headers)))
            url = request.url
            if url.startswith("https://www.raisin.com/"):
                return mock.fulfill(content_type="text/html",
                                    body="<title>Raisin</title><main>Dashboard</main>")
            if not url.startswith("https://api2.weltsparen.de/"):
                return mock.abort()
            if request.method == "OPTIONS":
                return mock.fulfill(status=204, headers=CORS)
            path = url.split("?", 1)[0][len("https://api2.weltsparen.de"):]
            if path in answers:
                status, headers, body = answers[path]
                return mock.fulfill(status=status, headers={**CORS, **headers}, body=body)
            if path.endswith("/active"):
                body = json.dumps([{"accounting": {"deposit_id": "FDA_t001"}}])
            elif path.endswith("/inactive"):
                body = json.dumps([])
            elif path == site.DOCUMENTS_PATH:
                body = json.dumps({"documents": [{"id": "d0001", "created": "2026-03-05",
                                                  "title": "Kontoauszug",
                                                  "document_type": "STATEMENT"}]})
            elif path == site.DOCUMENTS_PATH + "/d0001":
                return mock.fulfill(status=200, headers={**CORS, "content-type": "application/pdf"},
                                    body=PDF)
            else:
                return mock.abort()
            mock.fulfill(status=200, headers={**CORS, "content-type": "application/json"}, body=body)

        context.route("**/*", route)
        page = context.new_page()
        page.goto(PAGE_URL)
        page.evaluate("t => localStorage.setItem('auth_token', JSON.stringify({access_token: t}))",
                      TOKEN)
        site._RUN.clear()
        yield page, seen, answers
        site._RUN.clear()
        browser.close()


def api_requests(seen):
    return [(m, u, h) for m, u, h in seen
            if u.startswith("https://api2.weltsparen.de/") and m != "OPTIONS"]


def test_the_lists_and_the_file_are_get_requests_with_the_token_and_no_cookie(dashboard):
    page, seen, _ = dashboard
    docs = site.collect_documents(page)
    assert [d.key_part for d in docs] == ["FDA_t001:d0001"]
    assert site.fetch_file(page, "d0001") == PDF
    calls = api_requests(seen)
    assert len(calls) == 4
    for method, url, headers in calls:
        assert method == "GET"
        assert headers.get("authorization") == "Bearer " + TOKEN
        assert "cookie" not in headers, "the fetch sent the browser's cookies"
    assert calls[0][1].startswith("https://api2.weltsparen.de" + site.ACTIVE_PATH + "?customer_id=")
    assert calls[-1][1] == "https://api2.weltsparen.de" + site.DOCUMENTS_PATH + "/d0001?preview=true"
    # Nothing but the page itself and the API was ever asked for.
    assert {u.split("/")[2] for _, u, _ in seen} == {"www.raisin.com", "api2.weltsparen.de"}


def test_the_token_never_comes_back_to_python(dashboard):
    page, _, _ = dashboard
    url = site.API + site.ACTIVE_PATH + "?customer_id=" + CUSTOMER
    answer = intake.evaluate(page, site._API_JS, {"url": url, "want": "json"})
    assert TOKEN not in json.dumps(answer)
    pdf = intake.evaluate(page, site._API_JS,
                          {"url": site.API + site.DOCUMENTS_PATH + "/d0001?preview=true",
                           "want": "pdf"})
    assert TOKEN not in json.dumps(pdf) and base64.b64decode(pdf["b64"]) == PDF


@pytest.mark.parametrize("status", [302, 307])
def test_a_redirect_is_never_followed(dashboard, status):
    page, seen, answers = dashboard
    answers[site.ACTIVE_PATH] = (status, {"location": "https://api2.weltsparen.de/elsewhere"}, "")
    with pytest.raises(site.ListStopped):
        site.collect_documents(page)
    assert not any("/elsewhere" in u for _, u, _ in seen)


def test_the_page_script_refuses_another_host(dashboard):
    page, seen, _ = dashboard
    answer = intake.evaluate(page, site._API_JS, {"url": "https://evil.test/x", "want": "json"})
    assert answer == {"status": 0, "where": "offhost"}
    assert not any("evil.test" in u for _, u, _ in seen)


def test_a_page_with_no_token_asks_nothing(dashboard):
    page, seen, _ = dashboard
    page.evaluate("() => localStorage.removeItem('auth_token')")
    before = len(api_requests(seen))
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)
    assert len(api_requests(seen)) == before


def test_a_signed_out_api_is_a_sign_out(dashboard):
    page, _, answers = dashboard
    answers[site.INACTIVE_PATH] = (401, {"content-type": "application/json"}, "{}")
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)


def test_the_fetch_is_asked_for_with_no_cookie_and_no_redirect(dashboard):
    """A redirect answered by the router is followed past it on the real
    network, where it reaches nothing, so whether the page followed it
    cannot be seen there. What the page's script asked fetch for can."""
    page, _, _ = dashboard
    page.evaluate("""() => {
      window.__asked = [];
      const real = window.fetch;
      window.fetch = (url, init) => {
        window.__asked.push({method: init.method, credentials: init.credentials,
                             redirect: init.redirect});
        return real(url, init);
      };
    }""")
    site.collect_documents(page)
    site.fetch_file(page, "d0001")
    asked = page.evaluate("() => window.__asked")
    assert len(asked) == 4
    assert all(a == {"method": "GET", "credentials": "omit", "redirect": "error"} for a in asked)
