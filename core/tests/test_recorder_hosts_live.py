"""A recording in a real browser keeps a provider's own API on a host of its
own, and where a download came from, and nothing of anyone else's.

BBVA's list, messages and PDFs come from a host its app did not list yet,
and a recording of it kept none of them. Consorsbank's download opens a tab
that closes blank, and a recording of it kept no trace of the PDF's address
(#178). A fake page cannot say which frame a fetch came from or what a
browser reports as a download's address, so these drive Chromium. Every
host and value is invented.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://example.test"
API = "https://api.example.test"
VENDOR = "https://vendor.test"
MERCHANT = "QZ4XKRWPT7MVN"
SURNAME = "Zorvexquill"

BATCH = json.dumps([
    {"operationName": "documentList", "query": "{ documents { id } }",
     "variables": {"portfolioId": MERCHANT}},
    {"operationName": "unread", "query": "{ x }", "variables": {"who": SURNAME}},
])

DOCS = """
<h1>Documents</h1>
<button id="list" onclick='fetch("%s/graphql", {method: "POST",
  headers: {"content-type": "text/plain"}, body: %s});
  const f = document.createElement("iframe"); f.src = "%s/widget";
  document.body.appendChild(f);
  const s = document.createElement("script"); s.src = "%s/tag.js";
  document.head.appendChild(s);'>Show documents</button>
<a id="open" href="%s/dl" target="_blank">Download statement</a>
<a id="inline" href="data:application/pdf;base64,JVBERi0xLjQK%s" download="s.pdf">Save PDF</a>
""" % (API, json.dumps(BATCH), VENDOR, VENDOR, HOST, MERCHANT)

# The tab a download button opens. It starts the file and closes itself, so
# the person sees a blank tab come and go.
DL = """
<a id="f" href="/files/%s.pdf?token=%s">x</a>
<script>document.getElementById("f").click(); setTimeout(() => window.close(), 300);</script>
""" % (SURNAME, MERCHANT)

WIDGET = """
<script>fetch("%s/graphql", {method: "POST", headers: {"content-type": "text/plain"},
  body: "[]"});</script>
""" % API

# A vendor's tag, loaded into the provider's own frame, calling home. Its
# call comes from the provider's frame and is still not the provider's.
TAG = """fetch("%s/collect", {method: "POST", headers: {"content-type": "text/plain"},
  body: "[]"});""" % VENDOR


def safe(url: str) -> bool:
    try:
        p = urlsplit(url or "")
        return p.scheme == "https" and p.hostname == "example.test"
    except ValueError:
        return False


def _route(route):
    url = route.request.url
    if url.startswith(API):
        route.fulfill(status=200, content_type="application/json",
                      headers={"Access-Control-Allow-Origin": "*"},
                      body=json.dumps([{"data": {"documents": [{"id": MERCHANT}]}},
                                       {"data": {"unread": 1}}]))
    elif url.startswith(VENDOR + "/tag.js"):
        route.fulfill(status=200, content_type="application/javascript", body=TAG)
    elif url.startswith(VENDOR + "/collect"):
        route.fulfill(status=200, content_type="application/json",
                      headers={"Access-Control-Allow-Origin": "*"}, body="{\"ok\": 1}")
    elif url.startswith(VENDOR):
        route.fulfill(status=200, content_type="text/html", body=WIDGET)
    elif "/files/" in url:
        route.fulfill(status=200, content_type="application/pdf",
                      headers={"Content-Disposition": "attachment; filename=statement.pdf"},
                      body=b"%PDF-1.4\n%%EOF\n")
    elif url.startswith(HOST + "/dl"):
        route.fulfill(status=200, content_type="text/html", body=DL)
    else:
        route.fulfill(status=200, content_type="text/html", body=DOCS)


@pytest.fixture()
def context():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.route("**/*", _route)
    yield ctx
    browser.close()
    driver.stop()


def _start(ctx):
    page = ctx.new_page()
    page.goto("%s/docs" % HOST)
    rec = recorder.Recorder(page, is_safe_url=safe, provider="Testco")
    rec.start()
    return page, rec


def _no_value_in(report):
    text = json.dumps(report).lower()
    for canary in (MERCHANT, SURNAME, "portfolioid", "jvber"):
        assert canary.lower() not in text, "%s came out" % canary


def test_the_pages_own_call_to_its_api_host_is_kept_and_a_vendors_is_not(context):
    page, rec = _start(context)
    seen = []
    context.on("response", lambda r: seen.append((r.url, r.request.post_data)))
    page.click("#list")
    # The page's own batch, the widget's call from its frame and the tag's
    # call from the provider's frame, all three answered before Stop.
    for _ in range(100):
        if (any(u.startswith(API) and p != "[]" for u, p in seen)
                and any(u.startswith(API) and p == "[]" for u, p in seen)
                and any(u.startswith(VENDOR + "/collect") for u, p in seen)):
            break
        page.wait_for_timeout(100)
    else:
        pytest.fail("the three calls were never answered, so this proves nothing")
    page.wait_for_timeout(300)
    report = rec.stop()

    kept = [r for r in report["requests"] if r.get("on_the_providers_own_site") is False]
    assert len(kept) == 1, report["requests"]
    call = kept[0]
    assert call["batch"] == 2
    assert [i.get("operation") for i in call["post_items"]] == ["documentList", "unread"]
    assert call["shape"][0] == "batch of 2" and len(call["shape"]) == 3
    # The widget's own call to the same host, from a vendor's frame, and the
    # widget's page itself, are counted and not described.
    assert report["dropped"]["off_host_request"] >= 2
    _no_value_in(report)


def test_a_download_from_a_tab_that_closes_keeps_where_it_came_from(context):
    page, rec = _start(context)
    with context.expect_page() as info:
        page.click("#open")
    opened = info.value
    try:
        opened.wait_for_event("close", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    report = rec.stop()
    eff = report["steps"][0]["effect"]
    assert eff["new_tab"] is True and eff["download"] is True, eff
    assert eff["download_from"].startswith("https://example.test/files/"), eff
    assert eff["download_query_keys"] == ["token"]
    assert eff["download_off_host"] is False
    _no_value_in(report)


def test_a_file_written_into_the_address_keeps_only_its_type(context):
    page, rec = _start(context)
    with page.expect_download():
        page.click("#inline")
    page.wait_for_timeout(200)
    report = rec.stop()
    eff = report["steps"][0]["effect"]
    assert eff["download_from"] == "data:application/pdf", eff
    _no_value_in(report)
