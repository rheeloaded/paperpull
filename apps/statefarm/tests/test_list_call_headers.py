"""Each year is asked for with the headers the page's own call carried (#37).

The tester's Discover on 0.38.0 printed that the page's own read of the
list answered with four documents, and that every year the walk asked for,
the current one included, answered 401. The walk asked from inside the page
with cookies and an accept header and nothing more, while the page's own
call evidently carries more than that, most likely an authorization of its
own. So the walk now sends again the headers the page's own call sent,
the ones a page may set, and never a cookie, which the browser adds itself.

Every name, id and token here is invented.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site
import statefarm_docs as docs

THIS_YEAR = date.today().year
TOKEN = "Bearer invented-token-0001"
UI = site.BILLING_CANDIDATES[0]
LIST = "https://edocuments.statefarm.com/DocumentCenterProxyV1/customerMetadata"


def test_only_headers_a_page_may_set_are_sent_again():
    got = site._resendable_headers({
        "authorization": TOKEN, "x-sf-client": "web", "accept": "application/json",
        "cookie": "a=b", "host": "edocuments.statefarm.com", "origin": "https://x",
        "referer": "https://x/", "user-agent": "UA", "accept-encoding": "gzip",
        "sec-fetch-mode": "cors", "sec-ch-ua": "x", "content-length": "0", ":path": "/x"})
    assert got == {"authorization": TOKEN, "x-sf-client": "web", "accept": "application/json"}
    assert site._resendable_headers(None) == {}


def test_the_year_walk_sends_the_pages_own_headers():
    asked = []

    class _Page:
        def evaluate(self, js, arg=None):
            asked.append(arg)
            return {"status": 200, "type": "application/json", "body": {}}

    url = f"{LIST}?year=0"
    site._years_from(_Page(), url, -1, {}, headers={"authorization": TOKEN})
    assert asked and all(isinstance(a, list) and a[1] == {"authorization": TOKEN} for a in asked)
    assert asked[0][0].endswith("year=%d" % THIS_YEAR)


def test_with_no_headers_the_walk_asks_as_it_always_did():
    asked = []

    class _Page:
        def evaluate(self, js, arg=None):
            asked.append(arg)
            return {"status": 200, "type": "application/json", "body": {}}

    site._years_from(_Page(), f"{LIST}?year=0", -1, {})
    assert asked and all(isinstance(a, str) for a in asked)


def test_the_discovery_lines_say_what_the_page_sent_and_nothing_of_it():
    facts = {"page_list_answers": 1, "page_list_listed": 4, "page_list_kept": 4,
             "page_call_headers": 3, "page_call_authorization": True}
    lines = docs.discovery_lines(facts)
    assert "The page's own list call carried 3 header(s) of its own, an authorization among them." in lines
    assert TOKEN not in json.dumps(lines)
    facts["page_call_authorization"] = False
    assert any("no authorization among them" in ln for ln in docs.discovery_lines(facts))


# -- in a real browser ------------------------------------------------------------

UI_PAGE = """<!doctype html><html><body><h1>Document Center</h1><div id="rows"></div>
<script>
fetch("%s?year=0", {headers: {"Authorization": "%s", "X-SF-Client": "web",
                               "Accept": "application/json"}})
  .then(r => r.json()).then(b => {
    document.getElementById('rows').textContent = (b.data.attributes || []).length + ' documents';
  });
</script></body></html>""" % (LIST, TOKEN)


def _one(year, day):
    return {"creationDate": "%d-%s" % (year, day), "type": "Bill", "category": "Auto",
            "documentId": "doc-%d-%s" % (year, day), "filePathUrl": "/docs/%d-%s.pdf" % (year, day)}


def _answer(route):
    req = route.request
    if req.url.startswith(UI):
        return route.fulfill(status=200, content_type="text/html", body=UI_PAGE)
    if req.url.startswith(LIST):
        if req.headers.get("authorization") != TOKEN:
            return route.fulfill(status=401, content_type="text/html", body="<p>denied</p>")
        year = req.url.rsplit("year=", 1)[-1]
        per = {"0": [_one(THIS_YEAR, "09-12"), _one(THIS_YEAR, "04-16")],
               str(THIS_YEAR - 1): [_one(THIS_YEAR - 1, "10-02")],
               str(THIS_YEAR - 2): [_one(THIS_YEAR - 2, "03-30")]}.get(year, [])
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"data": {"attributes": per}}))
    route.abort()


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", _answer)
    yield ctx.new_page()
    browser.close()
    driver.stop()


def test_earlier_years_answer_when_asked_the_way_the_page_asks(page):
    facts: dict = {}
    got = site.collect_download_docs(page, facts)
    dates = sorted(d.date_text for d in got)
    assert dates == ["%d-03-30" % (THIS_YEAR - 2), "%d-10-02" % (THIS_YEAR - 1),
                     "%d-04-16" % THIS_YEAR, "%d-09-12" % THIS_YEAR], dates
    assert facts["page_call_headers"] >= 2 and facts["page_call_authorization"] is True
    statuses = {y["year"]: y.get("status") for y in facts["years"]}
    assert statuses[THIS_YEAR] == 200 and statuses[THIS_YEAR - 1] == 200
    assert TOKEN not in json.dumps(facts)
