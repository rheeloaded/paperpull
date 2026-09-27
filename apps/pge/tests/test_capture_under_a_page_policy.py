"""A blob read under the page's own security policy. From the second
review of round eight (#33).

The round eight repair read a bill that opened at a blob with the page's
own fetch. A page whose policy says connect-src 'self' refuses a fetch of
a blob address, and Salesforce documents that as its default. His history
is a Salesforce site, and its answers carry Salesforce's CSP setting. The
contributor met the same wall in his own pilot. His first blob capture
fetched it in the page, and the commit that made the capture work
replaced that with a download from the page that made the blob. That
download is not governed by connect-src, and it is the fallback now.

The history below is served with that policy. Every byte and address in
it is invented.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_site as site

HISTORY = "https://myaccount.pge.com/myaccount/s/bill-and-payment-history"
POLICY = "default-src 'self'; script-src 'self' 'unsafe-inline'; connect-src 'self'"
_BILL = "%PDF-1.4 an invented bill"

# His round three row, and a press that opens the bill in a new tab at a
# blob the page made. Plain text, so headless Chromium keeps it as a tab
# rather than turning it into a download. The bytes are what count.
ROW = """<html><body><table><tbody><tr class="rowbox">
  <td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td>
  <td></td>
  <td><div class="align-right"><a class="pdf-link">View Bill PDF</a></div></td>
  <td class="no-padding-right"><p class="payoffamount-divpara">$12.34</p></td>
</tr></tbody></table>
<script>
  window.presses = 0;
  document.querySelector('a.pdf-link').addEventListener('click', () => {
    window.presses++;
    const b = new TextEncoder().encode('%s');
    window.open(URL.createObjectURL(new Blob([b], {type: 'text/plain'})));
  });
</script></body></html>""" % _BILL

# A viewer in the page pointing at a blob the page made, the dialog shape.
VIEWER = """<html><body><h1>history</h1><div id="d" role="dialog"></div>
<script>
  const b = new TextEncoder().encode('%s');
  const u = URL.createObjectURL(new Blob([b], {type: 'text/plain'}));
  document.getElementById('d').innerHTML = '<iframe src="' + u + '"></iframe>';
</script></body></html>""" % _BILL


def _launch(body_for, policy=POLICY):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context(accept_downloads=True)
    ctx.set_default_timeout(30000)          # what pge_docs sets

    def serve(route):
        headers = {"content-type": "text/html"}
        if policy:
            headers["content-security-policy"] = policy
        route.fulfill(status=200, headers=headers, body=body_for(route.request.url))

    ctx.route("https://myaccount.pge.com/**", serve)
    ctx.route("https://www.pge.com/**", serve)
    return driver, browser, ctx


@pytest.fixture()
def history():
    driver, browser, ctx = _launch(lambda url: ROW)
    pg = ctx.new_page()
    pg.goto(HISTORY)
    yield pg
    browser.close()
    driver.stop()


def _download(page, tmp_path):
    from paperpull_core.journal import Journal
    out = tmp_path / "bill.pdf"
    j = Journal(page)
    site.set_journal(j)
    try:
        ok = site.download_bill(page, {"date_text": "2031-04-17", "row_index": 0,
                                       "page_number": 1}, out, {})
    finally:
        site.set_journal(None)
    results = [(e.get("outcome"), e.get("facts", {})) for e in j.report()["entries"]
               if e.get("kind") == "result"]
    return ok, out, results


def test_a_blob_tab_is_saved_when_the_policy_refuses_the_pages_fetch(history, tmp_path):
    """The reviewer's probe, as a test. The page's fetch of the blob is
    refused, and the download from the page that made it still works."""
    ok, out, results = _download(history, tmp_path)
    assert ok is True
    assert out.read_bytes() == _BILL.encode()
    assert history.evaluate("window.presses") == 1
    assert ("read the new tab", {"pge_origin": True, "bill": True, "by_download": True}) in results
    assert len(history.context.pages) == 1, "the tab is closed afterwards"


def test_the_page_really_does_refuse_its_own_fetch_here(history):
    """So the test above is about the policy and not about a fetch that
    would have worked anyway."""
    history.set_default_timeout(5000)
    with history.expect_popup() as info:
        history.click("a.pdf-link")
    tab = info.value
    tab.wait_for_url(lambda u: u.startswith("blob:"))
    assert site._pdf_from_blob_tab(history, tab, tab.url) is None


def test_a_blob_viewer_in_the_page_is_saved_under_the_same_policy():
    driver, browser, ctx = _launch(lambda url: VIEWER)
    try:
        pg = ctx.new_page()
        pg.goto(HISTORY)
        pg.wait_for_timeout(300)
        assert site._pdf_from_here(pg) == _BILL.encode()
    finally:
        browser.close()
        driver.stop()


def test_a_blob_from_another_origin_is_never_saved_and_the_tab_never_moves():
    """A link to a blob of another origin would move the tab instead of
    saving anything, so nothing is clicked unless the blob is the page's
    own. Here the page is on www.pge.com and the blob names myaccount."""
    driver, browser, ctx = _launch(lambda url: "<h1>home</h1>", policy="")
    try:
        pg = ctx.new_page()
        pg.goto("https://www.pge.com/en/home")
        heard = []
        pg.on("download", lambda d: heard.append(d))
        got = site._blob_by_download((pg,), "blob:https://myaccount.pge.com/0000-invented")
        assert got is None
        assert heard == []
        assert pg.url == "https://www.pge.com/en/home"
    finally:
        browser.close()
        driver.stop()


def test_the_new_tab_is_asked_only_after_the_page_that_made_the_blob(history, tmp_path, monkeypatch):
    """The new tab shows the browser's own PDF viewer on his machine, and a
    script asked to run in there has no time limit here. The page that made
    the blob is asked both ways first, its fetch and a download from it,
    and the tab only when neither gave the bill (third review of round
    eight). Under this policy the page's download is what works."""
    asked = []
    real = site._press_once

    class _Watched:
        """The real tab, with a note of every time a script is run in it."""
        def __init__(self, tab):
            self._tab = tab

        def __getattr__(self, name):
            return getattr(self._tab, name)

        def evaluate(self, *a, **k):
            asked.append("evaluate")
            return self._tab.evaluate(*a, **k)

        def expect_download(self, *a, **k):
            asked.append("expect_download")
            return self._tab.expect_download(*a, **k)

    def press(*a, **k):
        tab = real(*a, **k)
        return _Watched(tab) if tab is not None else None

    monkeypatch.setattr(site, "_press_once", press)
    ok, out, results = _download(history, tmp_path)
    assert ok is True and out.read_bytes() == _BILL.encode()
    assert asked == [], "the tab was asked while the page that made the blob could give it"
    assert ("read the new tab", {"pge_origin": True, "bill": True, "by_download": True}) in results


# Two bills whose presses each open a blob the page made, and the browser's
# hold for the several-files question, modeled in the page. The first save
# link made on the history is held. The next one lets the held one go
# first and its own a moment later, the order a queue lets them go when
# the person answers Allow. Every date and byte is invented.
HELD = """<html><body><table><tbody>
<tr class="rowbox"><td><div class="slds-col row-box">04/17/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right"><a class="pdf-link" id="a">View Bill PDF</a></div></td>
  <td><p class="payoffamount-divpara">$12.34</p></td></tr>
<tr class="rowbox"><td><div class="slds-col row-box">03/18/2031</div></td>
  <td><div class="slds-col row-box-td">Bill Charges</div></td><td></td>
  <td><div class="align-right"><a class="pdf-link" id="b">View Bill PDF</a></div></td>
  <td><p class="payoffamount-divpara">$56.78</p></td></tr>
</tbody></table>
<script>
  const open = (id, words) => document.getElementById(id).addEventListener('click', () => {
    const b = new TextEncoder().encode(words);
    window.open(URL.createObjectURL(new Blob([b], {type: 'text/plain'})));
  });
  open('a', '%PDF-1.4 invented bill A');
  open('b', '%PDF-1.4 invented bill B');
  window.held = [];
  window.released = 0;
  const click = HTMLAnchorElement.prototype.click;
  const fire = (href) => { const a = document.createElement('a'); a.href = href;
    a.download = 'x.pdf'; document.body.appendChild(a); click.call(a); a.remove(); };
  HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute('download') && this.href.startsWith('blob:')) {
      if (!window.released && window.held.length === 0) {
        window.held.push(this.href);
        return;
      }
      if (window.held.length) {
        const mine = this.href;
        window.held.splice(0).forEach(fire);
        window.released = 1;
        setTimeout(() => fire(mine), 400);
        return;
      }
    }
    return click.call(this);
  };
</script></body></html>"""


def test_a_held_download_of_an_earlier_bill_is_never_saved_as_the_next(monkeypatch, tmp_path):
    """The final review's probe, as a test. The app's own download waits
    took the first download the history started without looking at its
    address, so bill A's save, held back and let go during bill B's wait,
    was saved as bill B (final review of #33)."""
    monkeypatch.setattr(site, "_ADDRESSES_TAKEN", set())
    driver, browser, ctx = _launch(lambda url: HELD)
    try:
        pg = ctx.new_page()
        pg.goto(HISTORY)
        a_out, b_out = tmp_path / "a.pdf", tmp_path / "b.pdf"
        site.download_bill(pg, {"date_text": "2031-04-17", "row_index": 0,
                                "page_number": 1}, a_out, {})
        ok_b = site.download_bill(pg, {"date_text": "2031-03-18", "row_index": 1,
                                       "page_number": 1}, b_out, {})
        if a_out.exists():
            assert b"bill A" in a_out.read_bytes()
        if b_out.exists():
            assert b"bill A" not in b_out.read_bytes(), "bill A was saved under bill B's name"
        if ok_b:
            assert b_out.read_bytes() == b"%PDF-1.4 invented bill B"
    finally:
        browser.close()
        driver.stop()
