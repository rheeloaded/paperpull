"""A Document Center row that must be opened before its document exists.

His 0.34.0 Pilot pressed "View Documents1", watched "Payment Receipt -
Payment Receipt" appear, and stopped, because nothing pressed the
document itself. The recording he sent earlier showed that document
opening in a new tab (#37).

The rows here fold like an accordion, one open at a time, which is the
shape his trace fits. Opening every row first and then pressing the
wanted one again folds it away, which is why the last row is tried too.
The document opens in a new tab as a blob the page made, so nothing here
can reach the network.

Every date, name and vehicle here is invented.
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site

CENTER = "https://edocuments.statefarm.com/DocumentCenterUI/"

PAGE = """<!doctype html><html><body>
<h1>Document Center</h1>
%s
<script>
function openDoc(name) {
  const bytes = new TextEncoder().encode('%%PDF-1.4 ' + name);
  window.open(URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'})), '_blank');
}
function fetchDoc() {
  fetch('/DocumentCenterProxyV1/document/Jane_Q_Invented/file');
}
function toggle(pressed) {
  document.querySelectorAll('[role=row]').forEach(row => {
    const btn = row.querySelector('button.view');
    if (!btn) return;
    const open = btn === pressed && btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    row.querySelector('.docs').hidden = !open;
  });
}
</script>
</body></html>"""

D_RENEWAL, D_RECEIPT, D_DECL = "2026-03-14", "2026-05-08", "2026-01-27"

ROWS = [
    ("03/14/2026", "Renewal Notice - 2017 Invented Roadster"),
    ("05/08/2026", "Payment Receipt - Payment Receipt"),
    ("01/27/2026", "Declarations Page - Homeowners"),
]

# What the trace says about each revealed document. The type, and never the
# description, which on a real row can be a vehicle or a policy.
MASKED = {D_RENEWAL: "Renewal Notice - ...", D_RECEIPT: "Payment Receipt - ...",
          D_DECL: "Declarations Page - ..."}


def _one_row(when, doc, n, press):
    return ("<div role='row'><span class='when'>%s</span> <span>Sent by mail. Available online until %s</span>"
            "<button class='view' aria-expanded='false' onclick='toggle(this)'>View Documents%d</button>"
            "<div class='docs' hidden><a href='#' onclick=\"%s;return false\">%s</a></div>"
            "</div>" % (when, when[:6] + "2028", n, press, doc))


def _row_html(action="openDoc('%s')", rows=None):
    out = []
    for i, (when, doc) in enumerate(ROWS if rows is None else rows):
        out.append(_one_row(when, doc, i, action % doc if "%s" in action else action))
    return "".join(out)


def _rows():
    return PAGE % _row_html()


# Rows whose control is the document itself, with no View Documents in
# between, which is the other route download_bill takes.
DIRECT = [("03/14/2026", "Renewal Notice"), ("01/27/2026", "Declarations Page")]


def _direct_rows(action="openDoc('%s')"):
    return PAGE % "".join(
        "<div role='row'><span class='when'>%s</span> "
        "<a href='#' onclick=\"%s;return false\">%s</a></div>"
        % (when, action % doc if "%s" in action else action, doc) for when, doc in DIRECT)


# The same rows, drawn only once the page's own list call has answered and
# a moment has passed, the way the real Document Center fills itself. Until
# then the page holds one document control with no date on it, which the
# rows replace. That is the page a Pilot on 0.37.0 searched (#37).
SLOW_SCRIPT = """<script>
setTimeout(() => fetch('/DocumentCenterProxyV1/customerMetadata?year=2026')
  .then(r => r.json())
  .then(() => setTimeout(() => {
    document.getElementById('shell').remove();
    document.getElementById('rows').innerHTML = ROWS_HTML;
  }, DRAW_MS)), ASK_MS);
</script>"""


def _slow_rows(shell="<nav><a id='shell' href='#'>Policy documents</a></nav>",
               ask_ms=0, draw_ms=3000):
    body = (shell + "<div id='rows'></div>"
            + SLOW_SCRIPT.replace("ROWS_HTML", json.dumps(_row_html()))
            .replace("DRAW_MS", str(draw_ms)).replace("ASK_MS", str(ask_ms)))
    return PAGE % body


def _drive(html_for_center, extra_routes=()):
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    # Everything is answered here or refused, so no request leaves this machine.
    ctx.route("**/*", lambda r: r.abort())
    ctx.route("https://edocuments.statefarm.com/**", lambda r: r.fulfill(
        status=200, content_type="text/html", body=html_for_center()))
    for pattern, handler in extra_routes:
        ctx.route(pattern, handler)
    pg = ctx.new_page()
    pg.goto(CENTER)
    return driver, browser, pg


LIST_ANSWER = ("**/DocumentCenterProxyV1/customerMetadata**", lambda r: r.fulfill(
    status=200, content_type="application/json", body='{"data": {"attributes": []}}'))


@pytest.fixture()
def page():
    driver, browser, pg = _drive(_rows)
    yield pg
    browser.close()
    driver.stop()


@pytest.fixture()
def slow_page():
    driver, browser, pg = _drive(_slow_rows, [LIST_ANSWER])
    yield pg
    browser.close()
    driver.stop()


@pytest.mark.parametrize("when,title", [
    (D_RECEIPT, "Payment Receipt - Billing/Payments"),
    (D_DECL, "Declarations Page - Homeowners"),
])
def test_the_row_is_opened_once_and_its_document_is_saved(page, tmp_path, when, title):
    """His Pilot ended at the revealed document. The last row is the one
    that opening every row first would have left open and then folded."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(page, None, when, out, title=title, trace=trace), trace
    assert out.read_bytes().startswith(b"%PDF-")
    clicked = [t["control"] for t in trace if t.get("note") == "clicked"]
    assert clicked[0].startswith("View Documents") and len(clicked) == 2, clicked
    assert clicked[1] == MASKED[when]


def test_a_revealed_document_of_another_type_is_not_pressed(page, tmp_path):
    """The wrong document would be saved under this one's name and date.

    The list gave a path written with backslashes here rather than an
    address, which is not asked for, and the trace says which of the kinds
    of value it was without saying the value."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out, title="Renewal Notice - Auto",
                                  trace=trace, hint="\\\\invented-share\\Jane_Q_Invented\\receipt.pdf")
    assert not out.exists()
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents1"]
    said = [t for t in trace if t.get("note") == "no revealed document was pressed"]
    assert said and "0 revealed" in said[0]["why"], trace
    [have] = [t["have"] for t in trace if t.get("note") == "the document list gave no file address for this document"]
    assert have == "a path written with backslashes, which this app does not ask for"
    assert "Jane_Q_Invented" not in json.dumps(trace)


def test_the_date_in_the_row_is_the_issue_date_not_the_availability_date(page):
    """Each row also says "Available online until" a date in 2028."""
    assert sorted(site._control_dates(page)) == sorted([D_RENEWAL, D_RECEIPT, D_DECL])


# -- round eight, his 0.37.0 Pilot (#37) ---------------------------------------

def test_the_reload_waits_for_the_rows_before_looking_for_one(slow_page, tmp_path):
    """His file said the only control seen had "no date", the page had no rows, and
    its list call had not answered when the app looked. 0.34.2 stopped
    waiting at the first document control of any kind, so it searched a
    page whose rows were not drawn yet."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(slow_page, None, D_RECEIPT, out,
                              title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert out.read_bytes().startswith(b"%PDF-")
    [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
    assert loaded["list_answered"] and loaded["wanted_date_seen"], loaded
    # The rows are drawn three seconds after the list answers, so the wait
    # took about that long. Asserted well short of it, never on the edge.
    assert loaded["dated_controls"] == 3 and loaded["waited_ms"] >= 2000, loaded
    clicked = [t["control"] for t in trace if t.get("note") == "clicked"]
    assert clicked == ["View Documents1", "Payment Receipt - ..."], clicked


def test_a_dated_control_before_the_list_answers_does_not_end_the_wait(tmp_path):
    """A control reads its date from up to six levels of the page around
    it. One that finds a date before any row exists used to end the wait
    two seconds later with the list still unanswered. The list is asked for
    here four and a half seconds after the reload, well past that."""
    shell = "<div><span>Updated 02/02/2026</span> <a id='shell' href='#'>Policy documents</a></div>"
    driver, browser, pg = _drive(lambda: _slow_rows(shell, ask_ms=4500, draw_ms=300),
                                 [LIST_ANSWER])
    try:
        assert "2026-02-02" in site._control_dates(pg), "the shell control does carry a date"
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
        [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert loaded["list_answered"] and loaded["wanted_date_seen"], loaded
    finally:
        browser.close()
        driver.stop()


def test_the_wait_stops_at_once_on_a_sign_in_page(monkeypatch):
    """No row is coming on a sign-in page, and the wait used to sit there
    for all of it."""
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 8000)
    sign_in = lambda: "<!doctype html><html><body><input type='password'></body></html>"  # noqa: E731
    driver, browser, pg = _drive(sign_in)
    try:
        began = time.monotonic()
        facts = site._fresh_list(pg, D_RECEIPT)
        took = time.monotonic() - began
        assert facts.get("stopped_early"), facts
        # The first look is half a second in, the whole wait eight seconds.
        assert took < 5.0, "stopped at the first look, not after the whole wait (%.1f s)" % took
    finally:
        browser.close()
        driver.stop()


def test_the_wait_is_measured_by_the_clock(page, monkeypatch):
    """Reading the controls takes time on every pass, and counting only the
    half-second sleeps let a thirty second wait run far longer."""
    monkeypatch.setattr(site, "ROWS_WAIT_MS", 3000)

    def slow_dates(_page):
        time.sleep(1.5)
        return ["no date"]
    monkeypatch.setattr(site, "_control_dates", slow_dates)
    began = time.monotonic()
    facts = site._fresh_list(page, "2099-01-01")
    took = time.monotonic() - began
    # By the clock it ends at the first pass after three seconds, five at
    # most. Counting sleeps took six passes of two seconds, twelve. The
    # line is drawn well clear of both.
    assert took < 8.5, "%.1f s" % took
    assert facts["waited_ms"] >= 2500, facts


UUID = "0f8e7d6c-1a2b-4c3d-9e8f-7a6b5c4d3e2f"
NAMED = "/DocumentCenterProxyV1/document/Jane_Q_Invented/" + UUID


def test_a_file_address_that_is_not_a_pdf_is_traced_without_the_address(page, tmp_path):
    """Discovery keeps the list's file address from this round on, so the
    fetch runs for the first time. Its trace entry is a status, words for
    the content type and the answer, and facts about the address, and the
    row is still tried after."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(page, None, D_DECL, out, title="Declarations Page - Homeowners",
                              trace=trace, hint=NAMED), trace
    assert out.read_bytes().startswith(b"%PDF-")
    [said] = [t for t in trace if t.get("note") == "filePathUrl did not answer with a PDF"]
    assert said == {"note": "filePathUrl did not answer with a PDF", "status": 200, "type": "html",
                    "answered": "html", "bytes": said["bytes"], "absolute": False,
                    "address": {"host": "edocuments.statefarm.com",
                                "starts_with": "DocumentCenterProxyV1", "segments": 4,
                                "ends_in_pdf": False, "has_query": False,
                                "same_host_as_page": True}}, said
    written = json.dumps(trace)
    assert UUID not in written and "Jane_Q_Invented" not in written


def test_a_refused_file_address_says_its_status(tmp_path):
    """A refusal, a missing file and an empty answer all used to read
    "nothing" with 0 bytes, which cannot say whether the address is any
    use at all."""
    refused = ("**/DocumentCenterProxyV1/document/**", lambda r: r.fulfill(
        status=403, content_type="text/html", body="<p>no</p>"))
    driver, browser, pg = _drive(_rows, [refused])
    try:
        trace = []
        site.download_bill(pg, None, D_DECL, tmp_path / "doc.pdf",
                           title="Declarations Page - Homeowners", trace=trace, hint=NAMED)
        [said] = [t for t in trace if t.get("note") == "filePathUrl did not answer with a PDF"]
        assert (said["status"], said["type"], said["answered"]) == (403, "html", "nothing"), said
    finally:
        browser.close()
        driver.stop()


def test_a_file_address_that_answers_with_a_zip_is_taken_on_the_first_ask(tmp_path):
    """A tax form can come as a ZIP holding its PDF, which the docs module
    opens. Refused here, the row was pressed after it and State Farm was
    asked a second time for the same file."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Declarations.pdf", b"%PDF-1.4\n% an invented declarations page\n%%EOF\n")
    archive = buf.getvalue()
    asked = []

    def answer(route):
        asked.append(route.request.url)
        route.fulfill(status=200, content_type="application/zip", body=archive)

    driver, browser, pg = _drive(_rows, [("**/DocumentCenterProxyV1/document/**", answer)])
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_DECL, out, title="Declarations Page - Homeowners",
                                  trace=trace, hint=NAMED), trace
        assert out.read_bytes() == archive, "the row was pressed instead"
        assert len(asked) == 1, asked
    finally:
        browser.close()
        driver.stop()


def test_the_request_census_does_not_hear_the_file_address(page, tmp_path):
    """The census wrote each path into the failure file with only
    number-shaped parts masked, so a name in a file address would reach a
    file he is asked to post. It is not listening for that one fetch, and
    it is listening again for the reload after it. And since every part of
    a path is now a word on the fixed list or its shape, a census that did
    hear the address would keep only its shape."""
    from paperpull_core.api_census import Requests
    census = Requests(page, site.is_safe_url)
    census.start()
    site.download_bill(page, None, D_DECL, tmp_path / "doc.pdf",
                       title="Declarations Page - Homeowners", trace=[], hint=NAMED,
                       census=census)
    paths = [e["path"] for e in census.report()["seen"]]
    assert not [p for p in paths if "Jane_Q_Invented" in p], paths
    assert [p for p in paths if p.startswith("/DocumentCenterUI")], paths

    # A census listening hears the address and keeps only its shape.
    heard = Requests(page, site.is_safe_url)
    heard.start()
    site._fetch_with_status(page, "https://edocuments.statefarm.com" + NAMED, ("statefarm.com",))
    page.wait_for_timeout(300)
    paths = [e["path"] for e in heard.report()["seen"]]
    assert [p for p in paths if "/document/aaaa_a_aaaaaaaa/" in p], paths
    assert not [p for p in paths if "Jane_Q_Invented" in p], paths


PDF_ANSWER = ("**/DocumentCenterProxyV1/document/**", lambda r: r.fulfill(
    status=200, content_type="application/pdf", body=b"%PDF-1.4 invented"))


def _listening(page):
    from paperpull_core.api_census import Requests
    census = Requests(page, site.is_safe_url)
    census.start()
    return census


def _paths(census):
    return [e["path"] for e in census.report()["seen"]]


def test_the_request_census_does_not_hear_what_pressing_a_document_asks_for(tmp_path):
    """Pressing the revealed document is what first reaches the document's
    own address, and here the press asks for it from this tab. The census
    is not listening for that press, and listens again once it is over."""
    driver, browser, pg = _drive(lambda: PAGE % _row_html("fetchDoc()"), [PDF_ANSWER])
    try:
        census = _listening(pg)
        assert site.download_bill(pg, None, D_RECEIPT, tmp_path / "doc.pdf",
                                  title="Payment Receipt - Billing/Payments", trace=[], census=census)
        assert not [p for p in _paths(census) if "Jane_Q_Invented" in p], _paths(census)
        heard = len(_paths(census))
        pg.goto(CENTER)
        pg.wait_for_timeout(300)
        assert len(_paths(census)) > heard, "listening again once the press is over"
    finally:
        browser.close()
        driver.stop()


def test_the_request_census_does_not_hear_what_pressing_a_document_control_asks_for(tmp_path):
    """The same on the route where the row's control is the document."""
    driver, browser, pg = _drive(lambda: _direct_rows("fetchDoc()"), [PDF_ANSWER])
    try:
        census = _listening(pg)
        assert site.download_bill(pg, None, "2026-03-14", tmp_path / "doc.pdf",
                                  title="Renewal Notice - Auto", trace=[], census=census)
        assert not [p for p in _paths(census) if "Jane_Q_Invented" in p], _paths(census)
    finally:
        browser.close()
        driver.stop()


def test_a_census_that_was_not_listening_is_not_started(page, tmp_path):
    """Pausing a census that was not listening used to start it at the end
    of the pause, and it then heard the reload and everything after."""
    from paperpull_core.api_census import Requests
    census = Requests(page, site.is_safe_url)
    site.download_bill(page, None, D_DECL, tmp_path / "doc.pdf", title="Declarations Page - Homeowners",
                       trace=[], hint=NAMED, census=census)
    assert census.report()["seen"] == []


def test_a_file_address_that_answers_with_a_pdf_is_saved_without_pressing_anything(tmp_path):
    pdf = ("**/DocumentCenterProxyV1/document/**", lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4 invented"))
    driver, browser, pg = _drive(_rows, [pdf])
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_RENEWAL, out, title="Renewal Notice - Auto",
                                  trace=trace, hint="/DocumentCenterProxyV1/document/" + UUID)
        assert out.read_bytes() == b"%PDF-1.4 invented"
        assert not [t for t in trace if t.get("note") == "clicked"], trace
    finally:
        browser.close()
        driver.stop()


def test_a_record_that_stands_for_two_documents_is_neither_fetched_nor_pressed(page, tmp_path):
    """Its address could be either document's, and the row it is found by
    could be either one's too. A save under it would be marked done for
    good and the other document never fetched, so nothing is asked for,
    loaded or pressed."""
    asked = []

    def answer(route):
        asked.append(1)
        route.fulfill(status=200, content_type="application/pdf", body=b"%PDF-1.4 the other one")
    page.context.route("**/DocumentCenterProxyV1/document/**", answer)
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_DECL, out, title="Declarations Page - Homeowners",
                                  trace=trace, hint=NAMED, shared=True), trace
    assert not asked and not out.exists() and not requests, requests
    assert trace == [{"note": "two documents in the list share this date, type and category",
                      "so": "one record cannot stand for both, so nothing was fetched or pressed"}]
    assert page.locator("button.view[aria-expanded='true']").count() == 0


def test_two_rows_on_one_date_are_refused_and_nothing_is_saved(tmp_path):
    """Two rows carry one date, each with a Renewal Notice, one for a car
    and one for a house. They are different documents with different keys.
    The first row with the date used to be pressed, and its car's notice
    was saved under the house's name. Which row is this document's cannot
    be told from the date, so neither is pressed."""
    rows = [("03/14/2026", "Renewal Notice - 2017 Invented Roadster"),
            ("03/14/2026", "Renewal Notice - 12 Invented Lane"),
            ("05/08/2026", "Payment Receipt - Payment Receipt")]
    driver, browser, pg = _drive(lambda: PAGE % _row_html(rows=rows))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out,
                                      title="Renewal Notice - Homeowners", trace=trace), trace
        assert not out.exists()
        assert not [t for t in trace if t.get("note") == "clicked"], trace
        [said] = [t for t in trace if t.get("note") == "more than one control on the page carries this date"]
        assert said == {"note": "more than one control on the page carries this date", "controls": 2,
                        "so": "which row is this document's is not known, so none was pressed"}
        assert pg.locator("button.view[aria-expanded='true']").count() == 0
    finally:
        browser.close()
        driver.stop()


def _change_before_the_press(monkeypatch, page, js):
    """Run `js` in the page after the control is found and before it is
    pressed, which is when a page still settling can move it. The first
    thing either route does after the find is read every control on the
    page, so the change is made there."""
    real = site._control_texts
    done = []

    def reading(pg, *a, **k):
        if not done:
            done.append(1)
            page.evaluate(js)
        return real(pg, *a, **k)
    monkeypatch.setattr(site, "_control_texts", reading)


# The receipt's row is the second row. Each change leaves its control
# something other than the one that was checked.
_RECEIPT_ROW = "document.querySelectorAll('[role=row]')[1]"
CHANGES = {
    "its name changed": _RECEIPT_ROW + ".querySelector('button.view').textContent = 'View Documents9'",
    "it no longer carries this date": _RECEIPT_ROW + ".querySelector('.when').textContent = '06/09/2026'",
    "2 controls carry this date now": "document.body.insertAdjacentHTML('beforeend', %s)"
                                      % json.dumps(_one_row("05/08/2026", "Payment Receipt - Payment Receipt",
                                                            8, "openDoc('the other receipt')")),
    "it left the page": _RECEIPT_ROW + ".remove()",
}


@pytest.mark.parametrize("why", sorted(CHANGES))
def test_a_row_control_that_changed_before_the_press_is_not_pressed(page, tmp_path, monkeypatch, why):
    """The control is found, every control on the page is read, and only
    then is it pressed. Its name and date are read again right before the
    press, and it has to be the only control with that date still."""
    _change_before_the_press(monkeypatch, page, CHANGES[why])
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert not out.exists()
    assert not [t for t in trace if t.get("note") == "clicked"], trace
    assert {"note": "the row's control changed before it was pressed, so nothing was pressed",
            "why": why} in trace, trace
    assert page.locator("button.view[aria-expanded='true']").count() == 0


def test_the_control_pressed_is_the_node_that_was_checked(page, tmp_path, monkeypatch):
    """A row drawn above the wanted one after the find moves every control
    down one. "The second control" is then another row's, and the node that
    was checked is still the wanted row's, which is the one pressed."""
    _change_before_the_press(monkeypatch, page, (
        "document.querySelector('[role=row]').insertAdjacentHTML('beforebegin', %s)"
        % json.dumps(_one_row("02/02/2026", "Payment Receipt - Payment Receipt", 7,
                              "openDoc('a receipt from another row')"))))
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(page, None, D_RECEIPT, out,
                              title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert out.read_bytes() == b"%PDF-1.4 Payment Receipt - Payment Receipt"
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == [
        "View Documents1", "Payment Receipt - ..."], trace


def test_a_document_control_is_saved_when_it_is_the_row_itself(tmp_path):
    driver, browser, pg = _drive(_direct_rows)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 Renewal Notice"
    finally:
        browser.close()
        driver.stop()


def test_a_document_control_that_changed_before_the_press_is_not_pressed(tmp_path, monkeypatch):
    """The same check on the other route, where the row's control is the
    document itself."""
    driver, browser, pg = _drive(_direct_rows)
    try:
        _change_before_the_press(monkeypatch, pg,
                                 "document.querySelector('[role=row] a').textContent = 'Renewal Notice 2'")
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert not [t for t in trace if t.get("note") == "clicked"], trace
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "its name changed"} in trace, trace
    finally:
        browser.close()
        driver.stop()


def test_a_failed_press_is_not_made_through_the_page_once_the_control_changed(page, tmp_path):
    """A press can wait eight seconds before it fails, and then the control
    is pressed through the page. It is checked again first."""
    pressed = []

    class _Control:
        def scroll_into_view_if_needed(self, timeout=None):
            pass

        def click(self, timeout=None):
            raise Exception("Timeout 8000ms exceeded.")

        def evaluate(self, js):
            pressed.append(js)
    answers = iter(["", "its name changed"])
    trace = []
    assert not site._catch_pdf(page, _Control(), "Renewal Notice", tmp_path / "doc.pdf", trace,
                               None, check=lambda: next(answers, "its name changed"))
    assert not pressed, "nothing was pressed through the page"
    assert trace == [
        {"note": "click failed", "control": "another control", "why": "timed out"},
        {"note": "the control changed while the press waited, so it was not pressed through the page",
         "why": "its name changed"}], trace


def test_a_revealed_document_the_guard_refuses_says_so_without_its_description(tmp_path):
    """A description that acts is refused, however well the name is shaped.
    The trace says it was a document the guard refused, and the guard's own
    word for why, which "another control" could not. A money noun in a
    description, "Limited" on a vehicle say, no longer refuses a document
    (#37, test_a_description_that_names_money)."""
    rows = [("03/14/2026", "Renewal Notice - Cancel 2017 Invented Limited")]
    driver, browser, pg = _drive(lambda: PAGE % _row_html(rows=rows))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents0"]
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["appeared"] == ["Renewal Notice - ..., refused by the guard for cancel"], row
        assert row["refused_by_the_guard"] == 1 and row["look_like_documents"] == 0, row
        [said] = [t for t in trace if t.get("note") == "no revealed document was pressed"]
        assert said["why"] == "what the row revealed looks like a document and the guard refuses it"
        written = json.dumps(trace)
        assert "Invented" not in written and "Limited" not in written, written
    finally:
        browser.close()
        driver.stop()


def test_a_revealed_documents_description_never_reaches_the_trace(page, tmp_path):
    """A revealed document is "<type> - <description>", and the description
    of a Renewal Notice is the vehicle. He took his own out of the
    recording by hand. The trace names the type and nothing after it."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert site.download_bill(page, None, D_RENEWAL, out, title="Renewal Notice - Auto",
                              trace=trace), trace
    written = json.dumps(trace)
    assert "Roadster" not in written and "Invented" not in written, written
    [row] =[t for t in trace if t.get("note") == "the row's documents"]
    assert row["appeared"] == ["Renewal Notice - ..."] and row["wanted_type"] == "Renewal Notice"
    assert row["of_the_wanted_type"] == 1 and row["expanded_after"] == "true", row


def test_an_answer_the_press_brings_is_traced_without_its_address(tmp_path):
    """Pressing a revealed document is what first reaches the document's
    own address. Every answer on statefarm.com that arrives then is in the
    trace as facts, never as the address it came from."""
    driver, browser, pg = _drive(lambda: PAGE % _row_html("fetchDoc()"), [PDF_ANSWER])
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
        [answer] = [t for t in trace if "status" in t and "address" in t and "note" not in t]
        assert answer == {"status": 200, "type": "pdf", "address": {
            "host": "edocuments.statefarm.com", "starts_with": "DocumentCenterProxyV1",
            "segments": 4, "ends_in_pdf": False, "has_query": False,
            "same_host_as_page": True}}, answer
        assert "Jane_Q_Invented" not in json.dumps(trace)
    finally:
        browser.close()
        driver.stop()


# -- round eight, third repair after review (#37) --------------------------------

# Rows drawn once the page's own list answers, then drawn again with new
# nodes, the way a page that answers a second call can.
REDRAW_SCRIPT = """<script>
fetch('/DocumentCenterProxyV1/customerMetadata?year=2026')
  .then(r => r.json())
  .then(() => {
    const draw = () => { document.getElementById('rows').innerHTML = ROWS_HTML; };
    draw();
    REDRAWS.forEach(ms => setTimeout(draw, ms));
  });
</script>"""


def _redrawn_rows(redraws=tuple(range(300, 3001, 300))):
    return PAGE % ("<div id='rows'></div>"
                   + REDRAW_SCRIPT.replace("ROWS_HTML", json.dumps(_row_html()))
                   .replace("REDRAWS", json.dumps(list(redraws))))


def test_a_row_drawn_again_after_it_appeared_is_pressed_once_it_holds_still(tmp_path):
    """A page that drew its rows and drew them again a moment later took
    the press on the first drawing's node, and the next drawing folded the
    row away, so nothing was saved. The wanted row's control has to stay
    the same node for a moment before it is pressed.

    The rows here are drawn again every 300 ms for three seconds, so a
    press made while they still move is always folded away before the
    document it revealed can be pressed, and one made after is not."""
    driver, browser, pg = _drive(_redrawn_rows, [LIST_ANSWER])
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 Payment Receipt - Payment Receipt"
        [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert loaded["rows_redrawn"] >= 1 and loaded["wanted_date_seen"], loaded
    finally:
        browser.close()
        driver.stop()


def test_the_wanted_row_holds_still_for_a_moment_before_it_is_pressed(page):
    """Two looks at the same node half a second apart are not enough, since
    a page can draw its rows again a second later. On a page that never
    moves the wait still lasts SETTLE_MS past the first sight of the date,
    about two seconds in all, where stopping at the first sight took half a
    second and at the second look one. The line sits between them."""
    facts = site._fresh_list(page, D_RECEIPT)
    assert facts["wanted_date_seen"] and facts["rows_redrawn"] == 0, facts
    assert facts["waited_ms"] >= 1700, facts


def test_a_row_folded_away_after_the_press_says_its_control_left_the_page(tmp_path):
    """When the page draws its rows again right after the press, the node
    that was pressed still says it is open. The trace says the node left
    the page, which a row that revealed nothing would not."""
    rows = (_row_html().replace("onclick='toggle(this)'",
                                "onclick='toggle(this); setTimeout(redraw, 100)'"))
    html = PAGE % ("<div id='rows'>%s</div><script>const ROWS = %s;"
                   "function redraw() { document.getElementById('rows').innerHTML = ROWS; }</script>"
                   % (rows, json.dumps(_row_html())))
    driver, browser, pg = _drive(lambda: html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, D_RECEIPT, out,
                                      title="Payment Receipt - Billing/Payments", trace=trace), trace
        assert not out.exists()
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["control_after_the_press"] == "left the page", row
    finally:
        browser.close()
        driver.stop()


LONG = "Renewal Notice - 2021 Invented Motorworks Grand Tourer Touring Edition"


def test_a_revealed_document_with_a_long_name_is_found_and_saved(tmp_path):
    """What a press revealed is read with every name cut to sixty
    characters, and a name that long was looked for as the whole name, so
    a long vehicle description left the document unpressed."""
    assert len(LONG) > site._CUT_AT
    driver, browser, pg = _drive(lambda: PAGE % _row_html(rows=[("03/14/2026", LONG)]))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 " + LONG.encode()
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == [
            "View Documents0", "Renewal Notice - ..."], trace
        assert "Invented" not in json.dumps(trace)
    finally:
        browser.close()
        driver.stop()


def test_a_refused_word_past_the_sixtieth_character_still_keeps_the_press_away(tmp_path):
    """The name that appeared is cut before "pay now", which the guard
    refuses anywhere in a description. The node found is read whole and the
    guard is asked again."""
    name = "Renewal Notice - 2021 Invented Motorworks Grand Tourer Touring, pay now"
    assert "pay" not in name[:site._CUT_AT].lower() and site.is_revealed_document(name[:site._CUT_AT])
    assert not site.is_revealed_document(name)
    driver, browser, pg = _drive(lambda: PAGE % _row_html(rows=[("03/14/2026", name)]))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents0"]
        [said] = [t for t in trace if t.get("note") == "no revealed document was pressed"]
        assert said["why"] == "the guard refuses the document's whole name", said
        written = json.dumps(trace)
        assert "Motorworks" not in written and "Invented" not in written, written
    finally:
        browser.close()
        driver.stop()


def test_a_revealed_document_whose_name_for_screen_readers_is_refused_is_not_pressed(tmp_path):
    """A control's words and the name it gives a screen reader can differ.
    The guard is asked about both before the document is pressed."""
    html = PAGE % _row_html(rows=[("03/14/2026", "Renewal Notice - 2017 Invented Roadster")]).replace(
        "<a href='#'", "<a href='#' aria-label='Pay Now - Renewal Notice'")
    driver, browser, pg = _drive(lambda: html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        [said] = [t for t in trace if t.get("note") == "no revealed document was pressed"]
        assert said["why"] == "the guard refuses the document's whole name", said
    finally:
        browser.close()
        driver.stop()


# The receipt revealed in the second row. Each change leaves it something
# other than the document that was checked, after it was found and before
# it is pressed.
_RECEIPT_LINK = "document.querySelectorAll('[role=row]')[1].querySelector('.docs a')"
DOC_CHANGES = {
    "its name changed": _RECEIPT_LINK + ".textContent = 'Payment Receipt - Another Receipt'",
    "it left the page": _RECEIPT_LINK + ".remove()",
    "2 visible controls carry its name now": (
        _RECEIPT_LINK + ".insertAdjacentHTML('afterend', "
        "\"<a href='#' onclick=\\\"openDoc('another receipt');return false\\\">"
        "Payment Receipt - Payment Receipt</a>\")"),
}


@pytest.mark.parametrize("why", sorted(DOC_CHANGES))
def test_a_revealed_document_that_changed_before_its_press_is_not_pressed(page, tmp_path,
                                                                          monkeypatch, why):
    """The row's own control is read again right before its press. The
    document it reveals gets the same check before its own press."""
    real = site._snapshot
    done = []

    def changing(dl_dir):
        if not done:
            done.append(1)
            page.evaluate(DOC_CHANGES[why])
        return real(dl_dir)
    monkeypatch.setattr(site, "_snapshot", changing)
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert not out.exists() and len(page.context.pages) == 1
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents1"], trace
    assert {"note": "the control changed before it was pressed, so nothing was pressed",
            "why": why} in trace, trace


# Rows whose one control is the document itself and carries its own link,
# the shape of the route that fetches a control's link before any press.
LINKED = """<!doctype html><html><body><h1>Document Center</h1>
<div role='row'><span class='when'>03/14/2026</span> <a href='/docs/renewal.pdf'>Renewal Notice</a></div>
<div role='row'><span class='when'>01/27/2026</span> <a href='/docs/decl.pdf'>Declarations Page</a></div>
</body></html>"""

LINKED_PDFS = {"/docs/renewal.pdf": b"%PDF-1.4 the renewal notice",
               "/docs/decl.pdf": b"%PDF-1.4 the declarations page",
               "/docs/other-decl.pdf": b"%PDF-1.4 another declarations page"}


def _linked_page(monkeypatch, html=LINKED):
    """A page of linked rows, and a stand-in for the fetch of a control's own
    link that answers from LINKED_PDFS and lists what it was asked for, so
    nothing leaves this machine."""
    driver, browser, pg = _drive(lambda: html)
    fetched = []

    def fake_fetch(page, target, **how):
        fetched.append(target.split("statefarm.com", 1)[-1])
        return LINKED_PDFS.get(fetched[-1])
    monkeypatch.setattr(site, "_fetch_pdf", fake_fetch)
    return driver, browser, pg, fetched


def _between_the_find_and_the_link(monkeypatch, page, label, js):
    """Run `js` in the page when the guard is asked about `label`, which is
    after the control was found and before its link is read."""
    real = site.is_safe_control
    done = []

    def asking(name):
        if not done and name == label:
            done.append(1)
            page.evaluate(js)
        return real(name)
    monkeypatch.setattr(site, "is_safe_control", asking)


def test_a_row_drawn_above_after_the_find_does_not_change_whose_link_is_fetched(tmp_path, monkeypatch):
    """The control used to be "the nth control", looked up again when its
    link was read. A row drawn above it moved every control down one, and
    the renewal notice's link was fetched and saved as the declarations
    page. The control is now the node whose name and date were read."""
    driver, browser, pg, fetched = _linked_page(monkeypatch)
    try:
        _between_the_find_and_the_link(monkeypatch, pg, "Declarations Page", (
            "document.querySelector('[role=row]').insertAdjacentHTML('beforebegin', "
            "\"<div role='row'><span>02/02/2026</span> <a href='#'>ID Card</a></div>\")"))
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "2026-01-27", out, title="Declarations Page - Homeowners",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 the declarations page"
        assert fetched == ["/docs/decl.pdf"], fetched
    finally:
        browser.close()
        driver.stop()


def test_a_control_given_to_another_row_before_its_link_is_read_is_not_fetched(tmp_path, monkeypatch):
    """A page that reuses a node for another row changes its date and its
    link together. The link used to be read with no check before it, and
    that other row's document was fetched and saved under this one's name.
    The link is read in the same read that checks the name and the date."""
    driver, browser, pg, fetched = _linked_page(monkeypatch)
    try:
        _between_the_find_and_the_link(monkeypatch, pg, "Declarations Page", (
            "const row = document.querySelectorAll('[role=row]')[1];"
            "row.querySelector('.when').textContent = '02/02/2026';"
            "row.querySelector('a').setAttribute('href', '/docs/other-decl.pdf');"))
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-01-27", out, title="Declarations Page - Homeowners",
                                      trace=trace), trace
        assert not out.exists() and fetched == [], fetched
        assert {"note": "the control changed before its link was read, so nothing was fetched or pressed",
                "why": "it no longer carries this date"} in trace, trace
        assert not [t for t in trace if t.get("note") == "clicked"], trace
    finally:
        browser.close()
        driver.stop()


def test_a_document_control_that_names_another_type_is_neither_fetched_nor_pressed(tmp_path, monkeypatch):
    """A row whose one control is a Declarations Page, on the date of a
    Renewal Notice that was asked for, was saved as the Renewal Notice."""
    html = LINKED.replace("03/14/2026", "03/15/2026").replace("01/27/2026", "03/14/2026")
    driver, browser, pg, fetched = _linked_page(monkeypatch, html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and fetched == [] and len(pg.context.pages) == 1
        assert not [t for t in trace if t.get("note") == "clicked"], trace
        assert {"note": "the control for this date names another type of document",
                "names": "Declarations Page", "wanted_type": "Renewal Notice",
                "so": "it was not fetched or pressed"} in trace, trace
        # The same control is taken when it is the type asked for.
        trace = []
        assert site.download_bill(pg, None, "2026-03-14", out, title="Declarations Page - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 the declarations page"
    finally:
        browser.close()
        driver.stop()


def test_the_type_a_control_names_comes_from_its_own_words():
    assert site._named_type("Renewal Notice") == "renewalnotice"
    assert site._named_type("View Declarations Page PDF") == "declarationspage"
    assert site._named_type("Renewal Notice - 2017 Invented Roadster") == "renewalnotice"
    assert site._named_type("Download ID Cards") == "idcards"
    assert site._named_type("View PDF") == "" and site._named_type("View Documents2") == ""
    assert site._same_type("idcards", "idcard") and site._same_type("renewalnotice", "renewalnotice")
    assert not site._same_type("declarations", "declarationspage")
    assert not site._same_type("", "renewalnotice")


VIEWER = """<!doctype html><html><body><p>A viewer</p><script>
setInterval(() => fetch('/DocumentCenterProxyV1/document/Jane_Q_Invented/status'), 200);
</script></body></html>"""


def test_a_press_that_moves_the_tab_is_left_before_the_census_listens_again(tmp_path, monkeypatch):
    """A press can move this tab to the document's own page, which is not a
    PDF, and the core leaves the tab there. The census listened again
    while the tab stayed, and heard what that page kept asking for, with
    the name in its path. The tab goes back to the documents page first."""
    move = "location.href = '/DocumentInformationUI/view/Jane_Q_Invented'"
    driver, browser, pg = _drive(lambda: PAGE % _row_html(move), [
        ("**/DocumentInformationUI/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=VIEWER)),
        ("**/DocumentCenterProxyV1/document/**", lambda r: r.fulfill(
            status=200, content_type="application/json", body="{}"))])
    try:
        def press_and_get_nothing(page, el, label, out_path, trace=None, dl_dir=None, check=None,
                                  own=()):
            el.click()
            page.wait_for_url("**/DocumentInformationUI/**")
            page.wait_for_timeout(800)
            return False
        monkeypatch.setattr(site, "_catch_pdf", press_and_get_nothing)
        census = _listening(pg)
        trace = []
        assert not site.download_bill(pg, None, D_RECEIPT, tmp_path / "doc.pdf",
                                      title="Payment Receipt - Billing/Payments", trace=trace,
                                      census=census)
        pg.wait_for_timeout(1500)
        assert not [p for p in _paths(census) if "Jane_Q_Invented" in p], _paths(census)
        assert pg.url.startswith(CENTER), pg.url
        [back] = [t for t in trace if str(t.get("note", "")).startswith("the press left this tab")]
        assert back["address"]["starts_with"] == "DocumentInformationUI"
        assert "Jane_Q_Invented" not in json.dumps(trace)
    finally:
        browser.close()
        driver.stop()


class _NoPage:
    """Enough of a page for _unheard and _catch_pdf, with no browser, where
    waiting takes no time."""
    url = CENTER

    class context:  # noqa: N801
        pages: list = []

        @staticmethod
        def on(*a):
            pass

        @staticmethod
        def remove_listener(*a):
            pass

    def on(self, *a):
        pass

    def remove_listener(self, *a):
        pass

    def wait_for_timeout(self, ms):
        pass

    def get_by_role(self, *a, **k):
        raise Exception("no page here")

    def evaluate(self, js):
        return ""


def test_a_census_whose_state_cannot_be_read_is_stopped_and_not_started():
    """Whether the census is listening is read off the core's Requests. If
    that can no longer be read, it used to be taken as listening and started
    again after the block, which starts one that was not listening."""
    class _Census:
        def __init__(self):
            self.calls = []

        def stop(self):
            self.calls.append("stop")

        def start(self):
            self.calls.append("start")
    census = _Census()
    with site._unheard(_NoPage(), census):
        pass
    assert census.calls == ["stop"]


def test_the_core_census_still_says_whether_it_is_listening():
    """_unheard reads Requests._started. A rename in the core fails here
    before it can make the app start a census that was not listening."""
    from paperpull_core.api_census import Requests
    census = Requests(_NoPage(), site.is_safe_url)
    assert census._started is False
    census.start()
    assert census._started is True
    census.stop()
    assert census._started is False


class _Lands:
    """A control whose press is followed by a PDF landing in the folder."""
    def __init__(self, folder, name, gone=()):
        self.folder, self.name, self.gone = folder, name, gone

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def click(self, timeout=None):
        for g in self.gone:
            (self.folder / g).unlink()
        (self.folder / self.name).write_bytes(b"%PDF-1.4 " + self.name.encode())


def test_a_pdf_that_lands_while_an_earlier_download_is_unfinished_is_not_taken(tmp_path):
    """A download an earlier press started can finish during this press,
    and whatever lands in the folder was taken as this press's own and
    saved under this document's name."""
    folder = tmp_path / "downloads"
    folder.mkdir()
    (folder / "Unconfirmed 1.crdownload").write_bytes(b"%PDF-1.4 half")
    out = tmp_path / "doc.pdf"
    trace = []
    control = _Lands(folder, "earlier.pdf", gone=["Unconfirmed 1.crdownload"])
    assert not site._catch_pdf(_NoPage(), control, "Renewal Notice", out, trace, folder)
    assert not out.exists() and (folder / "earlier.pdf").exists()
    assert {"note": "a download from an earlier press had not finished, "
                    "so the download folder was not read for this press", "unfinished": 1} in trace


def test_a_pdf_that_lands_in_a_folder_with_nothing_unfinished_is_taken(tmp_path):
    """The folder is still read when nothing is being written, and a
    download left half done long ago does not stop it."""
    import os
    folder = tmp_path / "downloads"
    folder.mkdir()
    stale = folder / "Unconfirmed 9.crdownload"
    stale.write_bytes(b"%PDF-1.4 half")
    old = time.time() - site.UNFINISHED_RECENT_S - 600
    os.utime(stale, (old, old))
    out = tmp_path / "doc.pdf"
    assert site._catch_pdf(_NoPage(), _Lands(folder, "mine.pdf"), "Renewal Notice", out, [], folder)
    assert out.read_bytes() == b"%PDF-1.4 mine.pdf"


def test_a_document_that_shares_its_date_and_type_with_another_is_not_looked_for_on_the_page(page, tmp_path):
    """A row is found by its date and its document by its type, and neither
    says the category. Another document with this date and type in another
    category could be the one a row holds, so no row is pressed for it."""
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out, title="Payment Receipt - Billing/Payments",
                                  trace=trace, twins=1), trace
    assert not out.exists()
    assert {"note": "another document in the list has this date and type", "others": 1,
            "so": "the page does not say which row is whose, so none was pressed"} in trace, trace
    assert not [t for t in trace if t.get("note") == "clicked"], trace
    assert page.locator("button.view[aria-expanded='true']").count() == 0


def test_its_own_file_address_is_still_asked_for(tmp_path):
    """The file address is this document's own entry in the list, so it is
    tried whatever else shares the date and type."""
    driver, browser, pg = _drive(_rows, [PDF_ANSWER])
    try:
        out = tmp_path / "doc.pdf"
        assert site.download_bill(pg, None, D_RENEWAL, out, title="Renewal Notice - Auto", trace=[],
                                  hint="/DocumentCenterProxyV1/document/" + UUID, twins=1)
        assert out.read_bytes() == b"%PDF-1.4 invented"
    finally:
        browser.close()
        driver.stop()


# -- round eight, fourth repair after review, a document belongs to its row (#37) --
#
# After the row's View Documents was pressed, the document it revealed was
# any new control of the wanted type anywhere on the page. A list that draws
# itself again after the press, keeping the open row by its place in the
# list, then had another row's document pressed and saved under this one's
# name. The document is pressed now only while the control that was pressed
# is still on the page, still carries this date, is still the only row that
# does, and holds the document inside its own row.

# Each page below counts the documents pressed, so a test can say that none
# was pressed at all, not only that none was saved.
_COUNTS_PRESSES = ("window.docsPressed = 0;\n"
                   "function pressDoc(tag) { window.docsPressed++; openDoc(tag); }")

# Rows kept as data and drawn whole from it, the open row remembered by its
# place in the list. Pressing a row draws the rows again with it open, and a
# moment later a newer document is added at the top and the rows are drawn
# again with the same place open, which is now the row above.
_BY_PLACE = """<div id='rows'></div><script>
%s
let data = [{when: '05/08/2026', doc: 'Payment Receipt - Payment Receipt'},
            {when: '03/14/2026', doc: 'Payment Receipt - Payment Receipt'}];
const NEWER = {when: '01/27/2026', doc: 'Declarations Page - Homeowners'};
let openAt = -1;
function rowHtml(r, i) {
  return "<div role='row'><span class='when'>" + r.when + "</span> "
    + "<button class='view' aria-expanded='" + (i === openAt) + "' onclick='press(" + i + ")'>"
    + "View Documents" + i + "</button><div class='docs'" + (i === openAt ? "" : " hidden") + ">"
    + "<a href='#' onclick=\\"pressDoc('the document of " + r.when + "');return false\\">"
    + r.doc + "</a></div></div>";
}
function draw() { document.getElementById('rows').innerHTML = data.map(rowHtml).join(''); }
function press(i) {
  openAt = i;
  draw();
  setTimeout(() => { data = [NEWER].concat(data); draw(); }, 150);
}
draw();
</script>""" % _COUNTS_PRESSES

# The same list patched in place by place, the way a list without keys is.
# Every node stays where it is and is given the words of whichever row now
# sits at its place.
_IN_PLACE = """<div id='rows'></div><script>
%s
let data = [{when: '05/08/2026', doc: 'Payment Receipt - Payment Receipt'},
            {when: '03/14/2026', doc: 'Payment Receipt - Payment Receipt'}];
const NEWER = {when: '01/27/2026', doc: 'Declarations Page - Homeowners'};
let openAt = -1;
function patch() {
  const list = document.getElementById('rows');
  data.forEach((r, i) => {
    let row = list.children[i];
    if (!row) {
      row = document.createElement('div');
      row.setAttribute('role', 'row');
      row.innerHTML = "<span class='when'></span> <button class='view'></button>"
        + "<div class='docs' hidden><a href='#'></a></div>";
      row.querySelector('button').onclick = () => press(i);
      list.appendChild(row);
    }
    row.querySelector('.when').textContent = r.when;
    const b = row.querySelector('button');
    b.textContent = 'View Documents' + i;
    b.setAttribute('aria-expanded', String(i === openAt));
    row.querySelector('.docs').hidden = i !== openAt;
    const a = row.querySelector('a');
    a.textContent = r.doc;
    a.onclick = () => { pressDoc('the document of ' + r.when); return false; };
  });
}
function press(i) {
  openAt = i;
  patch();
  setTimeout(() => { data = [NEWER].concat(data); patch(); }, 150);
}
patch();
</script>""" % _COUNTS_PRESSES

# Rows kept by key, so each row keeps its own node and its own words, and
# opened by place. After the newer document is added the pressed row is
# still there with its date, and the row opened is the one above it.
_BY_KEY = """<div id='rows'></div><script>
%s
let data = [{key: 'b', when: '05/08/2026', doc: 'Payment Receipt - Payment Receipt'},
            {key: 'c', when: '03/14/2026', doc: 'Payment Receipt - Payment Receipt'}];
const NEWER = {key: 'a', when: '01/27/2026', doc: 'Declarations Page - Homeowners'};
const kept = {};
let openAt = -1;
function rowFor(r) {
  if (!kept[r.key]) {
    const row = document.createElement('div');
    row.setAttribute('role', 'row');
    row.innerHTML = "<span class='when'></span> <button class='view'></button>"
      + "<div class='docs' hidden><a href='#'></a></div>";
    row.querySelector('.when').textContent = r.when;
    row.querySelector('a').textContent = r.doc;
    row.querySelector('a').onclick = () => { pressDoc('the document of ' + r.when); return false; };
    row.querySelector('button').onclick = () => press(r.key);
    kept[r.key] = row;
  }
  return kept[r.key];
}
function draw() {
  const list = document.getElementById('rows');
  data.forEach((r, i) => {
    const row = rowFor(r);
    const b = row.querySelector('button');
    b.textContent = 'View Documents' + i;
    b.setAttribute('aria-expanded', String(i === openAt));
    row.querySelector('.docs').hidden = i !== openAt;
    list.appendChild(row);
  });
}
function press(key) {
  openAt = data.findIndex(r => r.key === key);
  draw();
  setTimeout(() => { data = [NEWER].concat(data); draw(); }, 150);
}
draw();
</script>""" % _COUNTS_PRESSES


# The date as a heading over a block of rows, rows kept by key and opened by
# place. A newer notice on the same day is added to the block a moment after
# the press and opened in the pressed row's place. The pressed node stays,
# still carries the date from the heading, and the notice showing is inside
# the block the date was read from, so only the other row's own View
# Documents in that block says it is another row's.
_BY_KEY_UNDER_ONE_DATE = """<section id='day'><h3>03/14/2026</h3></section><script>
%s
let data = [{key: 'a', doc: 'Renewal Notice - 2017 Invented Roadster', tag: 'the roadster notice'}];
const NEWER = {key: 'b', doc: 'Renewal Notice - 2019 Invented Coupe', tag: 'the coupe notice'};
const kept = {};
let openAt = -1;
function rowFor(r) {
  if (!kept[r.key]) {
    const row = document.createElement('div');
    row.setAttribute('role', 'row');
    row.innerHTML = "<button class='view'></button><div class='docs' hidden><a href='#'></a></div>";
    row.querySelector('a').textContent = r.doc;
    row.querySelector('a').onclick = () => { pressDoc(r.tag); return false; };
    row.querySelector('button').onclick = () => press(r.key);
    kept[r.key] = row;
  }
  return kept[r.key];
}
function draw() {
  const day = document.getElementById('day');
  data.forEach((r, i) => {
    const row = rowFor(r);
    const b = row.querySelector('button');
    b.textContent = 'View Documents' + i;
    b.setAttribute('aria-expanded', String(i === openAt));
    row.querySelector('.docs').hidden = i !== openAt;
    day.appendChild(row);
  });
}
function press(key) {
  openAt = data.findIndex(r => r.key === key);
  draw();
  setTimeout(() => { data = [NEWER].concat(data); draw(); }, 150);
}
draw();
</script>""" % _COUNTS_PRESSES


def _only_the_row_was_pressed(pg, out, trace):
    """Nothing saved, no tab opened, no document pressed, and the one press
    the row's own View Documents."""
    assert not out.exists() and len(pg.context.pages) == 1
    assert pg.evaluate("window.docsPressed") == 0, "no document was pressed"
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents1"], trace


def test_a_row_drawn_above_after_the_press_does_not_have_its_document_saved_here(tmp_path):
    """The list keeps its open row by its place, and a newer document is
    added at the top a moment after the press. The rows are drawn again with
    new nodes, and the row open at that place is the one above, whose
    receipt was pressed and saved as this one. The node that was pressed is
    gone, so the row is found again by its date, and the receipt showing is
    not inside it. Nothing is pressed, as when a row that left the page was
    refused outright (round nine)."""
    driver, browser, pg = _drive(lambda: PAGE % _BY_PLACE)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out,
                                      title="Payment Receipt - Billing/Payments", trace=trace), trace
        _only_the_row_was_pressed(pg, out, trace)
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["control_after_the_press"] == "left the page" and row["of_the_wanted_type"] == 1, row
        assert {"note": "the row's control left the page after its press, so its row was looked for "
                        "again by this date", "rows_with_this_date": 1} in trace, trace
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "the document is not inside the row found again by this date"} in trace, trace
    finally:
        browser.close()
        driver.stop()


def test_a_list_patched_in_place_after_the_press_does_not_have_another_rows_document_saved(tmp_path):
    """The same list patched in place, the way a list without keys is. The
    node that was pressed stays on the page, and the row it sits in now
    shows the date and the receipt of the row above. It no longer carries
    this date, so the receipt showing in it is not this one."""
    driver, browser, pg = _drive(lambda: PAGE % _IN_PLACE)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out,
                                      title="Payment Receipt - Billing/Payments", trace=trace), trace
        _only_the_row_was_pressed(pg, out, trace)
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["control_after_the_press"] == "still on the page", row
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "the row's control no longer carries this date"} in trace, trace
    finally:
        browser.close()
        driver.stop()


def test_a_list_that_keeps_its_rows_but_opens_by_place_has_the_document_refused(tmp_path):
    """Rows kept by key and opened by place. The node that was pressed stays
    on the page, keeps this date and is still the only one with it, and the
    receipt showing is in the row above. It is not inside the row that was
    pressed, and the trace says where it was instead."""
    driver, browser, pg = _drive(lambda: PAGE % _BY_KEY)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out,
                                      title="Payment Receipt - Billing/Payments", trace=trace), trace
        _only_the_row_was_pressed(pg, out, trace)
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "the document is not inside the row that was pressed"} in trace, trace
        [where] = [t for t in trace if t.get("note") == "where the document sat against the row that was pressed"]
        assert where == {"note": "where the document sat against the row that was pressed",
                         "in_the_row": False, "in_the_element_after_the_row": False,
                         "in_the_rows_parent": True, "in_a_dialog": False}, where
    finally:
        browser.close()
        driver.stop()


def test_another_row_opened_under_the_same_date_heading_has_its_document_refused(tmp_path):
    """The date is a heading over a block of rows, so the block is what the
    pressed control reads its date from, and a notice in any row of it sits
    inside that block. A newer notice on the same day is added to the block
    and opened in the pressed row's place. The other row's own View
    Documents in the block carries the date too, which says the notice
    showing may be that row's, so it is not pressed."""
    driver, browser, pg = _drive(lambda: PAGE % _BY_KEY_UNDER_ONE_DATE)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out,
                                      title="Renewal Notice - Auto", trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert pg.evaluate("window.docsPressed") == 0, "no document was pressed"
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents0"], trace
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "another View Documents inside the row carries this date now"} in trace, trace
    finally:
        browser.close()
        driver.stop()


# The receipt's row is the second row. Each change is made after its
# document was found and before it is pressed, and leaves the document
# itself as it was, named the same, on the page and the only one showing.
ROW_CHANGES = {
    "the row's control left the page": _RECEIPT_ROW + ".querySelector('button.view').remove()",
    "the row's control no longer carries this date": (
        _RECEIPT_ROW + ".querySelector('.when').textContent = '06/09/2026'"),
    "another control outside the row carries this date now": (
        "document.body.insertAdjacentHTML('beforeend', %s)"
        % json.dumps(_one_row("05/08/2026", "Payment Receipt - Payment Receipt", 8,
                              "openDoc('another receipt')"))),
    "the document is not inside the row that was pressed": "document.body.appendChild(%s)" % _RECEIPT_LINK,
}


@pytest.mark.parametrize("why", sorted(ROW_CHANGES))
def test_a_document_no_longer_tied_to_the_row_that_was_pressed_is_not_pressed(page, tmp_path,
                                                                              monkeypatch, why):
    """The document's own name and count were read again before its press,
    and nothing tied it to the row. Now the row's control has to be on the
    page, carry this date, be the only row that does and hold the document,
    all read in one call right before the press."""
    real = site._snapshot
    done = []

    def changing(dl_dir):
        if not done:
            done.append(1)
            page.evaluate(ROW_CHANGES[why])
        return real(dl_dir)
    monkeypatch.setattr(site, "_snapshot", changing)
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert not out.exists() and len(page.context.pages) == 1
    assert [t["control"] for t in trace if t.get("note") == "clicked"] == ["View Documents1"], trace
    assert {"note": "the control changed before it was pressed, so nothing was pressed",
            "why": why} in trace, trace


def test_a_document_whose_row_changed_while_its_press_waited_is_not_pressed_through_the_page(
        page, tmp_path, monkeypatch):
    """A press can wait eight seconds before it fails, and the document is
    then pressed through the page. Here something covers the document, so
    its press waits and fails, and three seconds into that wait the row that
    was pressed is given another date. The document is tied to its row again
    before it is pressed through the page, and it is not pressed."""
    real = site._snapshot
    done = []

    def covering(dl_dir):
        if not done:
            done.append(1)
            page.evaluate(
                "document.body.insertAdjacentHTML('beforeend', "
                "\"<div style='position:fixed;inset:0;z-index:9'></div>\");"
                "setTimeout(() => { %s.querySelector('.when').textContent = '06/09/2026'; }, 3000);"
                % _RECEIPT_ROW)
        return real(dl_dir)
    monkeypatch.setattr(site, "_snapshot", covering)
    out = tmp_path / "doc.pdf"
    trace = []
    assert not site.download_bill(page, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
    assert not out.exists() and len(page.context.pages) == 1
    assert [t["control"] for t in trace if t.get("note") == "click failed"] == ["Payment Receipt - ..."], trace
    assert {"note": "the control changed while the press waited, so it was not pressed through the page",
            "why": "the row's control no longer carries this date"} in trace, trace
    assert not [t for t in trace if t.get("note") == "clicked through the DOM instead"], trace


@pytest.mark.parametrize("renamed", ["View Documents 1", "Hide Documents"])
def test_an_opened_row_that_renames_its_button_still_has_its_document_saved(tmp_path, renamed):
    """A tester's file showed "View Documents 1" after a press where the
    button had said "View Documents1". Once pressed, the row's control is
    known by being on the page, by its date and by holding the document,
    never by its name, so a new name does not keep its document back."""
    rows = _row_html().replace("onclick='toggle(this)'",
                               "onclick='toggle(this); this.textContent = \"%s\"'" % renamed)
    driver, browser, pg = _drive(lambda: PAGE % rows)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, D_RECEIPT, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 Payment Receipt - Payment Receipt"
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == [
            "View Documents1", "Payment Receipt - ..."], trace
    finally:
        browser.close()
        driver.stop()


def test_a_document_found_by_its_name_has_to_read_as_the_document_that_appeared(tmp_path):
    """What appeared is read from each control's own words, and the control
    is then found by its accessible name, which is the name it gives a
    screen reader when it has one. A control named for screen readers as
    the receipt that appeared, whose own words are another document, was
    taken for the receipt."""
    html = PAGE % ("<div role='row'><span class='when'>05/08/2026</span> "
                   "<a href='#' aria-label='Payment Receipt - Payment Receipt'>"
                   "Declarations Page - Homeowners</a></div>")
    driver, browser, pg = _drive(lambda: html)
    try:
        el, name, why = site._revealed_document(pg, {"Payment Receipt - Payment Receipt"},
                                                "Payment Receipt - Billing/Payments")
        assert el is None and name == "", name
        assert why == "the control found by that name does not read as that document", why
    finally:
        browser.close()
        driver.stop()


_TYPELESS = ("<div role='row'><span class='when'>01/27/2026</span> <span>Declarations Page</span> "
             "<a href='#' onclick=\"openDoc('the declarations page');return false\">View PDF</a></div>")


def test_a_control_that_names_no_type_is_not_saved_as_another_type_its_row_names(tmp_path):
    """A row's one control says "View PDF" and the row says Declarations
    Page. The control's own words name no type, so nothing stopped it being
    saved as the Renewal Notice asked for on that date. The row's words are
    read in the same read as the control's name and date."""
    driver, browser, pg = _drive(lambda: PAGE % _TYPELESS)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-01-27", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert not [t for t in trace if t.get("note") == "clicked"], trace
        assert {"note": "the control for this date names no type and its row names another type of document",
                "names": "Declarations Page", "wanted_type": "Renewal Notice",
                "so": "it was not fetched or pressed"} in trace, trace
        # The same control is taken for the type its row names.
        trace = []
        assert site.download_bill(pg, None, "2026-01-27", out, title="Declarations Page - Homeowners",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 the declarations page"
    finally:
        browser.close()
        driver.stop()


def test_a_control_that_names_no_type_is_not_fetched_for_another_type_its_row_names(tmp_path, monkeypatch):
    """The same with a link of its own, which is fetched before any press.
    The row's words are read before the link is."""
    html = ("<!doctype html><html><body><h1>Document Center</h1>"
            "<div role='row'><span class='when'>01/27/2026</span> <span>Declarations Page</span> "
            "<a href='/docs/decl.pdf'>View PDF</a></div></body></html>")
    driver, browser, pg, fetched = _linked_page(monkeypatch, html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-01-27", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and fetched == [], fetched
        assert not [t for t in trace if t.get("note") == "clicked"], trace
    finally:
        browser.close()
        driver.stop()


def test_a_control_that_names_no_type_in_a_row_that_names_none_is_refused(tmp_path):
    """A row that names no type says nothing for the control either. It was
    taken as the document asked for, which saved whatever it was under that
    name, so now it is refused and left for the next run (final review)."""
    html = PAGE % ("<div role='row'><span class='when'>03/14/2026</span> "
                   "<a href='#' onclick=\"openDoc('the only document');return false\">View PDF</a></div>")
    driver, browser, pg = _drive(lambda: html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                      trace=trace)
        assert not out.exists()
        assert any(t.get("note") == "the control for this date names no type and its row does "
                                    "not name the type asked for" for t in trace), trace
    finally:
        browser.close()
        driver.stop()


def test_a_control_that_names_no_type_in_a_row_naming_an_unknown_type_is_refused(tmp_path):
    """The final review's probe. The row says Proof of Insurance, a type
    this file does not know, so nothing counted against it and it was saved
    as the Renewal Notice asked for on that date."""
    html = PAGE % ("<div role='row'><span class='when'>01/27/2026</span> <span>Proof of Insurance</span> "
                   "<a href='#' onclick=\"openDoc('a proof of insurance');return false\">View PDF</a></div>")
    driver, browser, pg = _drive(lambda: html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-01-27", out, title="Renewal Notice - Auto",
                                      trace=trace)
        assert not out.exists()
        assert any(t.get("note") == "the control for this date names no type and its row does "
                                    "not name the type asked for" for t in trace), trace
    finally:
        browser.close()
        driver.stop()


def test_a_control_that_names_no_type_in_a_row_naming_the_wanted_type_is_saved(tmp_path):
    """The row says what the control is, so it is taken."""
    html = PAGE % ("<div role='row'><span class='when'>03/14/2026</span> Renewal Notice "
                   "<a href='#' onclick=\"openDoc('the renewal notice');return false\">View PDF</a></div>")
    driver, browser, pg = _drive(lambda: html)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == b"%PDF-1.4 the renewal notice"
    finally:
        browser.close()
        driver.stop()


def test_the_types_a_row_names_are_all_read():
    """A row that names the wanted type and another cannot say which one a
    control that names none is, so the other one is enough to refuse it."""
    assert site._other_type_named("01/27/2026 Declarations Page View PDF", "renewalnotice") == \
        "declarationspage"
    assert site._other_type_named("03/14/2026 Renewal Notice View PDF", "renewalnotice") == ""
    assert site._other_type_named("03/14/2026 Renewal Notice and Declarations Page", "renewalnotice") == \
        "declarationspage"
    assert site._other_type_named("03/14/2026 ID Cards", "idcard") == ""
    assert site._other_type_named("03/14/2026 View PDF Billing/Payments", "renewalnotice") == ""
    assert site._other_type_named("", "renewalnotice") == ""


def test_the_grace_starts_over_when_the_wanted_date_drops_out(monkeypatch):
    """Once the list has answered, the wait ends after four passes that do
    not show the wanted date. Those passes were counted from the start, so a
    date that showed once and was gone the next pass, while the page drew
    its rows again, ended the wait at that pass with nothing held still.
    The count starts over when the wanted date drops out."""
    driver, browser, pg = _drive(_rows)
    try:
        # The page's own address stands in for the list call, so the list has
        # answered before the first look and every pass is counted.
        monkeypatch.setattr(site, "DOCS_API_RE", re.compile("DocumentCenterUI"))
        script = [["2026-05-08"]] * 3 + [["2026-05-08", "2026-03-14"], ["2026-05-08"]]
        seen = []

        def dates(_page):
            seen.append(script[len(seen)] if len(seen) < len(script) else ["2026-05-08", "2026-03-14"])
            return seen[-1]
        monkeypatch.setattr(site, "_control_dates", dates)
        monkeypatch.setattr(site, "_controls_for",
                            lambda p, iso: [(p.query_selector("h1"), "View Documents1")])
        facts = site._fresh_list(pg, "2026-03-14")
        assert facts["list_answered"] and facts["rows_redrawn"] == 1, facts
        assert "2026-03-14" in seen[-1], "the wait ended where the date showed and held, %s" % seen
        # The drop is the fifth pass, and the date then holds for SETTLE_MS
        # from the sixth, several passes more. Asserted well short of that.
        assert len(seen) >= 7, seen
    finally:
        browser.close()
        driver.stop()


# -- what a trace may say, from a list ------------------------------------------

def test_the_facts_about_an_address_come_from_a_list():
    other = site.url_mask("https://docs.statefarm.com/Smith/renewal.pdf?x=Smith", CENTER)
    assert other == {"host": "another statefarm.com host", "starts_with": "other",
                     "segments": 2, "ends_in_pdf": True, "has_query": True,
                     "same_host_as_page": False}
    assert site.url_mask("https://elsewhere.example/Smith")["host"] == "off statefarm.com"
    assert site.url_mask("blob:https://edocuments.statefarm.com/" + UUID) == {
        "host": "blob", "on_statefarm": True}
    assert site.url_mask("") == {"host": "none"}
    assert site.url_mask(CENTER)["starts_with"] == "DocumentCenterUI"


def test_an_address_that_is_not_https_says_so():
    """Only an https address is ever asked for. One that is not would
    otherwise read like an address on a State Farm host that was."""
    assert "scheme" not in site.url_mask(CENTER)
    plain = site.url_mask("http://edocuments.statefarm.com/DocumentCenterUI/")
    assert plain["scheme"] == "http" and plain["host"] == "edocuments.statefarm.com"
    assert site.url_mask("//edocuments.statefarm.com/Jane_Q_Invented")["scheme"] == "none"
    odd = site.url_mask("ftp://elsewhere.example/Jane_Q_Invented")
    assert odd["scheme"] == "other" and odd["host"] == "off statefarm.com"
    assert "Jane" not in json.dumps(odd)


def test_a_control_is_named_from_a_list():
    assert site._label_mask("View Documents2") == "View Documents2"
    assert site._label_mask("Renewal Notice - 2017 Invented Roadster") == "Renewal Notice - ..."
    assert site._label_mask("Renewal Notice - 2017 Invented Limited") == "Renewal Notice - ..."
    assert site._label_mask("Renewal Notice - Cancel 2017 Invented Limited") == \
        "Renewal Notice - ..., refused by the guard for cancel"
    assert site._label_mask("Pay Now - Payment Receipt") == \
        "another type - ..., refused by the guard for pay"
    assert site._label_mask("Quilted Umbrella Rider - Jane Q Invented") == "another type - ..."
    assert site._label_mask("Download PDF") == "download pdf"
    assert site._label_mask("Jane Q Invented") == "another control"
    assert site._label_mask("") == "nothing"


def test_a_failed_press_is_a_fixed_phrase():
    """Playwright's message quotes the locator, which quotes the name."""
    e = Exception('Timeout 8000ms exceeded. waiting for get_by_role("link", '
                  'name="Renewal Notice - 2017 Invented Roadster")')
    assert site._click_failure(e) == "timed out"
    assert site._click_failure(Exception("<div> intercepts pointer events")) == \
        "something else on the page was in the way"


def test_a_tab_a_press_opened_is_described_by_facts():
    class _Tab:
        url = "https://edocuments.statefarm.com/DocumentInformationUI/view/Jane_Q_Invented"

        def evaluate(self, js):
            return "text/html; name=Jane_Q_Invented"
    [tab] = site._describe_tabs([_Tab()])
    assert "Jane_Q_Invented" not in json.dumps(tab)
    assert tab["content_type"] == "html" and tab["address"]["starts_with"] == "DocumentInformationUI"


def test_a_tab_that_moved_is_described_by_facts(tmp_path):
    """The core's own entry for this carries the address the tab moved to,
    which after a press is the document's own."""
    class _Moved:
        url = "https://edocuments.statefarm.com/DocumentInformationUI/view/Jane_Q_Invented"

        def evaluate(self, js):
            return "text/html"
    trace = []
    assert not site._take_same_tab(_Moved(), CENTER, tmp_path / "doc.pdf", trace)
    assert trace == [{"note": "the tab moved", "content_type": "html", "address": {
        "host": "edocuments.statefarm.com", "starts_with": "DocumentInformationUI", "segments": 3,
        "ends_in_pdf": False, "has_query": False, "same_host_as_page": True}}], trace


def test_no_trace_entry_is_scrubbed_page_text():
    """Every entry in download-attempt.json is built from a list. redact()
    keeps a segment that holds a name, and an error's own text quotes the
    control or the address, so neither may appear in a trace entry."""
    import ast
    src = Path(site.__file__).read_text(encoding="utf-8")
    bad = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and ("trace" in ast.unparse(node.func.value)
                                                    or ast.unparse(node.func.value) == "note")):
            text = ast.unparse(node)
            if "redact(" in text or "str(e" in text or "ct[" in text:
                bad.append("line %d: %s" % (node.lineno, text[:80]))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "note"):
            text = ast.unparse(node)
            if "redact(" in text or "str(e" in text:
                bad.append("line %d: %s" % (node.lineno, text[:80]))
    assert not bad, bad


# A document that opens a viewer tab, which fetches its PDF a moment later,
# the shape the recording and the census suggest. Invented bytes only.
_VIEWER = """<!doctype html><html><body><p>viewer</p><script>
setTimeout(() => fetch('/DocumentCenterProxyV1/document/right.pdf').then(r => r.arrayBuffer()), 1500);
</script></body></html>"""

_VIEWER_ROUTES = [
    ("**/DocumentInformationUI/**", lambda r: r.fulfill(status=200, content_type="text/html",
                                                        body=_VIEWER)),
    ("**/DocumentCenterProxyV1/document/right.pdf", lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4 the right document")),
    ("**/DocumentCenterProxyV1/document/other-tab.pdf", lambda r: r.fulfill(
        status=200, content_type="application/pdf", body=b"%PDF-1.4 a document another tab opened")),
]


def _rows_opening_a_viewer():
    return PAGE % _row_html(action="window.open('/DocumentInformationUI/view/abc', '_blank')")


def test_a_pdf_a_tab_already_open_loads_is_never_saved_as_the_document(tmp_path):
    """The final review's probe. The listener hears the whole browser, and
    over CDP that is the member's own. A State Farm PDF loading in a tab
    that was open before the press was saved under this document's name,
    while the document's own viewer was still fetching it."""
    driver, browser, pg = _drive(_rows_opening_a_viewer, _VIEWER_ROUTES)
    try:
        other = pg.context.new_page()
        other.goto(CENTER)
        other.evaluate("setInterval(() => fetch('/DocumentCenterProxyV1/document/other-tab.pdf'), 150)")
        pg.bring_to_front()
        out = tmp_path / "doc.pdf"
        trace = []
        ok = site.download_bill(pg, None, D_RECEIPT, out,
                                title="Payment Receipt - Billing/Payments", trace=trace)
        if out.exists():
            assert out.read_bytes() != b"%PDF-1.4 a document another tab opened"
        assert ok and out.read_bytes() == b"%PDF-1.4 the right document", trace
    finally:
        browser.close()
        driver.stop()


def test_the_documents_own_viewer_tab_is_still_saved(tmp_path):
    """The same press with no other tab open saves the right document."""
    driver, browser, pg = _drive(_rows_opening_a_viewer, _VIEWER_ROUTES)
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        ok = site.download_bill(pg, None, D_RECEIPT, out,
                                title="Payment Receipt - Billing/Payments", trace=trace)
        assert ok and out.read_bytes() == b"%PDF-1.4 the right document", trace
    finally:
        browser.close()
        driver.stop()


# -- round nine, his 0.37.1 Pilot (#37) ------------------------------------------
#
# His file said View Documents1 was pressed, a Renewal Notice appeared, and
# the button pressed had left the page, while a View Documents of the same
# number appeared as well. The Document Center draws the pressed row anew,
# with the documents inside the new row, and nothing was pressed after that
# because the node held was the old one. His census also showed the page
# asking for its list with a year in the query that is not four digits, so
# discovery never asked for an earlier year.

# Rows drawn from ROWS, closed. Pressing a row's button draws that row anew,
# open, with its document inside it and a button that names itself by
# OPENED, where N is the row's place. Neither button says aria-expanded, as in
# his file. With TWIN the press also draws another row with the same date
# right after it. With IN_DIALOG the document goes in a dialog that was on
# the page, hidden and empty, before the press. FILL is what fills ROWS and
# draws them.
_ANEW = """<div id='rows'></div><div role='dialog' id='dialog' hidden></div><script>
%s
const OPENED = OPENED_JSON;
const TWIN = TWIN_JSON;
const IN_DIALOG = IN_DIALOG_JSON;
let ROWS = [];
let openAt = -1;
function docLink(r) {
  const a = document.createElement('a');
  a.href = '#';
  a.textContent = r.doc;
  a.onclick = () => { pressDoc('the document of ' + r.when); return false; };
  return a;
}
function rowNode(r, i, open) {
  const row = document.createElement('div');
  row.setAttribute('role', 'row');
  row.innerHTML = "<span class='when'></span> <span>Sent by mail.</span> <button class='view'></button>";
  row.querySelector('.when').textContent = r.when;
  const b = row.querySelector('button');
  b.textContent = open ? OPENED.replace('N', String(i)) : 'View Documents' + i;
  b.onclick = () => press(i);
  if (open && !IN_DIALOG) {
    const docs = document.createElement('div');
    docs.className = 'docs';
    docs.appendChild(docLink(r));
    row.appendChild(docs);
  }
  return row;
}
function draw() {
  ROWS.forEach((r, i) => document.getElementById('rows').appendChild(rowNode(r, i, false)));
}
function press(i) {
  const list = document.getElementById('rows');
  const was = openAt;
  openAt = openAt === i ? -1 : i;
  [was, i].forEach(k => {
    if (k >= 0) list.children[k].replaceWith(rowNode(ROWS[k], k, k === openAt));
  });
  if (TWIN && openAt === i) {
    list.children[i].insertAdjacentElement('afterend', rowNode(
      {when: ROWS[i].when, doc: 'Payment Receipt - Another Receipt'}, ROWS.length, false));
  }
  if (IN_DIALOG) {
    const dialog = document.getElementById('dialog');
    dialog.replaceChildren(...(openAt === i ? [docLink(ROWS[i])] : []));
    dialog.hidden = openAt !== i;
  }
}
FILL
</script>""" % _COUNTS_PRESSES


def _anew(rows, opened="View Documents N", twin=False, fill=None, in_dialog=False):
    return PAGE % (_ANEW.replace("OPENED_JSON", json.dumps(opened))
                   .replace("TWIN_JSON", json.dumps(twin))
                   .replace("IN_DIALOG_JSON", json.dumps(in_dialog))
                   .replace("FILL", fill or "ROWS = %s;\ndraw();" % json.dumps(rows)))


_ANEW_ROWS = [{"when": "09/12/2026", "doc": "Payment Receipt - Payment Receipt"},
              {"when": "07/22/2026", "doc": "Payment Receipt - Payment Receipt"},
              {"when": "04/16/2026", "doc": "Renewal Notice - 2017 Invented Roadster"}]


@pytest.mark.parametrize("opened,when,title,button", [
    ("View DocumentsN", "2026-04-16", "Renewal Notice - Auto", "View Documents2"),
    ("View Documents N", "2026-04-16", "Renewal Notice - Auto", "View Documents2"),
    ("View Documents N", "2026-07-22", "Payment Receipt - Billing/Payments", "View Documents1"),
])
def test_a_row_drawn_anew_by_its_press_has_its_document_saved_from_that_row(tmp_path, opened, when,
                                                                            title, button):
    """His file. The row's View Documents was pressed, its Renewal Notice
    appeared, and the button pressed had left the page, so nothing more was
    pressed. The row is found again by its date now and its document is
    pressed from inside it. The receipt asked for is the one in the row with
    its date and not the other row's. A new button that names itself with a
    space appears in the trace the way his did."""
    driver, browser, pg = _drive(lambda: _anew(_ANEW_ROWS, opened))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, when, out, title=title, trace=trace), trace
        row_date = "%s/%s/%s" % (when[5:7], when[8:10], when[:4])
        assert out.read_bytes() == ("%%PDF-1.4 the document of %s" % row_date).encode()
        assert pg.evaluate("window.docsPressed") == 1
        masked = "%s - ..." % site._type_word(title)
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == [button, masked], trace
        [row] = [t for t in trace if t.get("note") == "the row's documents"]
        assert row["control_after_the_press"] == "left the page", row
        assert row["expanded_before"] == row["expanded_after"] == "absent", row
        assert row["appeared"] == ([masked, button] if " N" in opened else [masked]), row
        assert {"note": "the row's control left the page after its press, so its row was looked for "
                        "again by this date", "rows_with_this_date": 1} in trace, trace
        assert "Invented" not in json.dumps(trace)
    finally:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("drawn", ["before the press", "after the press"])
def test_two_rows_that_carry_the_date_have_no_document_pressed(tmp_path, drawn):
    """Two rows with one date cannot be told apart by it. Before the press
    nothing is pressed at all. After it the row cannot be found again as the
    only one with its date, so the document it revealed is not pressed, and
    the trace says how many rows carried the date."""
    rows = [{"when": "07/22/2026", "doc": "Payment Receipt - Payment Receipt"},
            {"when": "04/16/2026", "doc": "Renewal Notice - 2017 Invented Roadster"}]
    if drawn == "before the press":
        rows.insert(1, {"when": "07/22/2026", "doc": "Payment Receipt - Another Receipt"})
    driver, browser, pg = _drive(lambda: _anew(rows, twin=drawn == "after the press"))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-07-22", out,
                                      title="Payment Receipt - Billing/Payments", trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert pg.evaluate("window.docsPressed") == 0, "no document was pressed"
        clicked = [t["control"] for t in trace if t.get("note") == "clicked"]
        if drawn == "before the press":
            assert clicked == [], trace
            assert {"note": "more than one control on the page carries this date", "controls": 2,
                    "so": "which row is this document's is not known, so none was pressed"} in trace
        else:
            assert clicked == ["View Documents0"], trace
            [again] = [t for t in trace if t.get("note") == "the row's control left the page after "
                       "its press, so its row was looked for again by this date"]
            # How every View Documents read its date then, counted, since
            # the one row with it was not found.
            assert again == {"note": again["note"], "rows_with_this_date": 2, "openers": 3,
                             "with_this_date": 2, "with_another_date": 1, "only_days_ahead": 0,
                             "with_no_date": 0}, again
            assert {"note": "no revealed document was pressed",
                    "why": "2 rows carry this date after the press, so which one is this "
                           "document's is not known"} in trace, trace
    finally:
        browser.close()
        driver.stop()


# The renewal notice's row first, so the notice in the dialog reads that
# row's date from the page around it, and a Renewal Notice is a document
# control where a Payment Receipt is not.
_RENEWAL_FIRST = [_ANEW_ROWS[2], _ANEW_ROWS[0], _ANEW_ROWS[1]]


@pytest.mark.parametrize("rows,button", [(_ANEW_ROWS, "View Documents2"),
                                         (_RENEWAL_FIRST, "View Documents0")],
                         ids=["the third row", "the first row"])
def test_a_document_that_opens_in_a_dialog_is_not_pressed_and_the_trace_says_where_it_sat(
        tmp_path, rows, button):
    """Every failure file counted four dialogs, hidden ones included, so a
    dialog the press filled in would not change the count. His file points
    to the row, and a document outside its row is not pressed wherever it
    sits. The trace says it sat in a dialog, so the next file settles it.

    With the first row asked for, the notice in the dialog reads that row's
    date from the page around it. It was counted as another control outside
    the row then, and the trace never said where it sat."""
    driver, browser, pg = _drive(lambda: _anew(rows, in_dialog=True))
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert not site.download_bill(pg, None, "2026-04-16", out, title="Renewal Notice - Auto",
                                      trace=trace), trace
        assert not out.exists() and len(pg.context.pages) == 1
        assert pg.evaluate("window.docsPressed") == 0, "no document was pressed"
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == [button], trace
        assert {"note": "the control changed before it was pressed, so nothing was pressed",
                "why": "the document is not inside the row found again by this date"} in trace, trace
        [where] = [t for t in trace if str(t.get("note", "")).startswith("where the document sat")]
        assert where == {"note": "where the document sat against the row found again by this date",
                         "in_the_row": False, "in_the_element_after_the_row": False,
                         "in_the_rows_parent": False, "in_a_dialog": True}, where
    finally:
        browser.close()
        driver.stop()


# The same rows, filled from the page's own list call the way the Document
# Center fills itself, one row for each date. The call leaves the year empty,
# one of the values his file allows, since it held something other than four
# digits.
_FILLED_BY_THE_LIST = (
    "fetch('/DocumentCenterProxyV1/customerMetadata?year=').then(r => r.json()).then(body => {\n"
    "  const seen = {};\n"
    "  (body.data.attributes || []).forEach(e => {\n"
    "    if (seen[e.creationDate]) return;\n"
    "    seen[e.creationDate] = true;\n"
    "    ROWS.push({when: e.creationDate, doc: e.type + ' - ' + e.description});\n"
    "  });\n"
    "  draw();\n"
    "});")

THIS_YEAR = date.today().year


def _fills_itself():
    return _anew([], fill=_FILLED_BY_THE_LIST)


def _listed(when, kind, category, description, doc_id):
    """One document as the list answers for it, with every field his file
    showed and no file address, as for the document he tried."""
    return {"availableDate": when[:6] + str(int(when[6:]) + 2), "category": category,
            "clientId": "invented", "communicationId": "invented", "creationDate": when,
            "custIndexId": 1, "custViewCd": "invented", "deliveryType": "Mail",
            "description": description, "docSeqNum": 1, "docSetId": 1, "documentId": doc_id,
            "expirationDate": "", "filePathUrl": "", "partitionId": "invented",
            "policyId": "invented", "roleAccessSum": 1, "size": 1, "type": kind}


def _by_year():
    """What the list answers for each value of its year. Left empty, the
    page's own period, it answers with this year's."""
    y = THIS_YEAR
    this = [_listed("01/02/%d" % y, "Renewal Notice", "Auto", "2017 Invented Roadster", "invented-1"),
            _listed("01/01/%d" % y, "Payment Receipt", "Billing/Payments", "Payment Receipt", "invented-2")]
    last = [_listed("10/16/%d" % (y - 1), "Renewal Notice", "Auto", "2017 Invented Roadster", "invented-3"),
            _listed("07/22/%d" % (y - 1), "Payment Receipt", "Billing/Payments", "Payment Receipt",
                    "invented-4")]
    return {"": this, str(y): this, str(y - 1): last}


def _list_by_year(asked, answers):
    """The list call answered from `answers` by the year in its query, and
    each year it was asked for kept in `asked`, the page's own and the
    walk's alike. A year the app changed on the page's own call is read
    here as changed."""
    def answer(route):
        from urllib.parse import parse_qs, urlsplit
        year = parse_qs(urlsplit(route.request.url).query, keep_blank_values=True).get("year", [None])[0]
        asked.append(year)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"data": {"attributes": answers.get(year, [])}}))
    return ("**/DocumentCenterProxyV1/customerMetadata**", answer)


def _drive_by_year(asked, answers=None):
    driver, browser, pg = _drive(_fills_itself, [_list_by_year(asked, answers or _by_year())])
    pg.wait_for_selector("button.view")
    del asked[:]
    return driver, browser, pg


def test_discovery_asks_the_list_for_each_earlier_year_by_the_year_in_its_own_address():
    """His Discover found this year only and said the list's address carries
    no year to change, while his census showed the page's own call carrying
    year in its query. Its value is not four digits, and here it is left
    empty. The walk sets it to this year and to each earlier one, and stops
    after two years running with nothing in them."""
    asked = []
    driver, browser, pg = _drive_by_year(asked)
    try:
        y = THIS_YEAR
        facts = {}
        docs = site.collect_download_docs(pg, facts)
        assert sorted(d.date_text for d in docs) == [
            "%d-07-22" % (y - 1), "%d-10-16" % (y - 1), "%d-01-01" % y, "%d-01-02" % y], docs
        assert facts["year_in_address"] is False and facts["year_value"] == "left empty", facts
        assert [e["year"] for e in facts["years"]] == [y, y - 1, y - 2, y - 3], facts
        assert facts["years"][1] == {"year": y - 1, "status": 200, "type": "json", "listed": 2,
                                     "kept": 2}, facts
        assert facts["stopped"] == "two years running with nothing in them", facts
        # The page's own call, then the walk's, each with only the year changed.
        assert asked == ["", str(y), str(y - 1), str(y - 2), str(y - 3)], asked
        assert (facts["with_a_file_address"], facts["with_no_file_address"]) == (0, 4), facts
    finally:
        browser.close()
        driver.stop()


def test_an_older_document_is_saved_from_the_list_of_its_own_year(tmp_path):
    """The page draws the rows of its own period, so last year's documents
    have no row on it, and a download of one looked for its date on a page
    that could not carry it. The reload now asks the page's own list call for
    the document's year, changing nothing else, and the page draws that
    year's rows itself. Nothing but the row's View Documents and its
    document is pressed, and the change ends with the load."""
    asked = []
    driver, browser, pg = _drive_by_year(asked)
    try:
        y = THIS_YEAR
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "%d-10-16" % (y - 1), out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == ("%%PDF-1.4 the document of 10/16/%d" % (y - 1)).encode()
        [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert loaded["note"] == ("loaded the documents page again with its list asked for this "
                                  "document's year, and waited for its rows"), loaded
        assert loaded["year_asked"] == y - 1 and loaded["wanted_date_seen"], loaded
        assert (loaded["list_calls_changed"], loaded["list_calls_unchanged"]) == (1, 0), loaded
        assert [t["control"] for t in trace if t.get("note") == "clicked"] == [
            "View Documents0", "Renewal Notice - ..."], trace
        assert asked == [str(y - 1)], "the page asked for that year itself, %s" % asked
        # A page loaded afterwards asks for its own period again.
        del asked[:]
        pg.goto(CENTER)
        pg.wait_for_selector("button.view")
        assert asked == [""], asked
    finally:
        browser.close()
        driver.stop()


def test_a_document_from_this_year_is_looked_for_in_the_pages_own_period_first(tmp_path):
    """Every document found so far was in the page's own period, and that
    load is left as the page makes it."""
    asked = []
    driver, browser, pg = _drive_by_year(asked)
    try:
        y = THIS_YEAR
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "%d-01-02" % y, out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == ("%%PDF-1.4 the document of 01/02/%d" % y).encode()
        [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert "year_asked" not in loaded and loaded["wanted_date_seen"], loaded
        assert asked == [""], asked
    finally:
        browser.close()
        driver.stop()


def test_a_document_from_this_year_outside_the_pages_own_period_is_looked_for_in_its_year(tmp_path):
    """The page's own period need not be the whole year. A document the walk
    found in this year's list, with no row in the page's own period, is
    looked for in the list of its year next."""
    answers = _by_year()
    answers[""] = answers[""][:1]
    asked = []
    driver, browser, pg = _drive_by_year(asked, answers)
    try:
        y = THIS_YEAR
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "%d-01-01" % y, out,
                                  title="Payment Receipt - Billing/Payments", trace=trace), trace
        assert out.read_bytes() == ("%%PDF-1.4 the document of 01/01/%d" % y).encode()
        loads = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert [t.get("year_asked") for t in loads] == [None, y], loads
        assert not loads[0]["wanted_date_seen"] and loads[1]["wanted_date_seen"], loads
        assert asked == ["", str(y)], asked
    finally:
        browser.close()
        driver.stop()


def test_a_row_past_the_thirtieth_control_is_found_without_asking_the_list_for_its_year(tmp_path):
    """The wait reads the dates of the first thirty controls only. A row
    past them was not seen there, and a document from this year then had
    the list asked for its year, which rests on a guess, where one load used
    to find it. The row is looked for among every control once the page is
    expanded, and the list is asked for nothing the page did not ask for."""
    y = THIS_YEAR
    many = [_listed("01/%02d/%d" % (d, y), "Renewal Notice", "Auto", "2017 Invented Roadster",
                    "invented-%d" % d) for d in range(1, 32)]
    asked = []
    driver, browser, pg = _drive_by_year(asked, {"": many, str(y): many})
    try:
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "%d-01-31" % y, out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert out.read_bytes() == ("%%PDF-1.4 the document of 01/31/%d" % y).encode()
        [loaded] = [t for t in trace if str(t.get("note", "")).startswith("loaded the documents page")]
        assert "year_asked" not in loaded, loaded
        assert asked == [""], asked
    finally:
        browser.close()
        driver.stop()


def test_an_older_document_whose_own_year_ends_on_a_sign_in_page_is_looked_for_in_the_pages_own_period(
        tmp_path, monkeypatch):
    """A load for an older document's own year that ended early ended the
    search, before the page's own period was tried. Only a load of the
    page's own period ends it that way now."""
    y = THIS_YEAR
    rows = [{"when": "10/16/%d" % (y - 1), "doc": "Renewal Notice - 2017 Invented Roadster"}]
    driver, browser, pg = _drive(lambda: _anew(rows))
    try:
        real = site._fresh_list
        loads = []

        def ends_early_for_its_year(page, want="", year=None, answers=None):
            loads.append(year)
            if year is None:
                return real(page, want, answers=answers)
            page.evaluate("document.getElementById('rows').replaceChildren()")
            return {"waited_ms": 0, "list_answered": False, "dated_controls": 0,
                    "wanted_date_seen": False, "rows_redrawn": 0, "year_asked": year,
                    "stopped_early": "a sign-in page or a page off statefarm.com"}
        monkeypatch.setattr(site, "_fresh_list", ends_early_for_its_year)
        out = tmp_path / "doc.pdf"
        trace = []
        assert site.download_bill(pg, None, "%d-10-16" % (y - 1), out, title="Renewal Notice - Auto",
                                  trace=trace), trace
        assert loads == [y - 1, None], loads
        assert out.read_bytes() == ("%%PDF-1.4 the document of 10/16/%d" % (y - 1)).encode()
    finally:
        browser.close()
        driver.stop()


def test_a_change_to_the_list_call_is_taken_off_even_when_adding_it_raised():
    """page.route can add its handler and still raise. The change was taken
    off only when adding it had not raised, so it could stay on the page and
    change the next document's list call as well."""
    class _RouteRaises:
        url = CENTER

        def __init__(self):
            self.added, self.taken_off = [], []

        def on(self, *a):
            pass

        def remove_listener(self, *a):
            pass

        def route(self, url, handler):
            self.added.append((url, handler))
            raise Exception("added and then failed")

        def unroute(self, url, handler=None):
            self.taken_off.append((url, handler))

        def goto(self, *a, **k):
            raise Exception("no page here")
    pg = _RouteRaises()
    facts = site._fresh_list(pg, "2025-10-16", year=2025)
    assert facts.get("reloaded") is False, facts
    assert len(pg.added) == 1 and pg.taken_off == pg.added, (pg.added, pg.taken_off)


def test_documents_a_row_shows_five_seconds_after_its_press_are_found(tmp_path):
    """The row shows its documents five seconds after View Documents is
    pressed. Eight looks half a second apart used to wait well past four
    seconds on a real page, since each look read every control one at a
    time, and the core reads them in one call now, so the wait is kept by
    the clock (the review after the census that followed CI run
    36792330947)."""
    late = "<script>const shown = toggle; toggle = (b) => setTimeout(() => shown(b), 5000);</script>"
    driver, browser, pg = _drive(lambda: _rows().replace("</body>", late + "</body>"))
    try:
        out = tmp_path / "doc.pdf"
        trace: list = []
        assert site.download_bill(pg, None, D_RECEIPT, out, title="Payment Receipt - Billing/Payments",
                                  trace=trace), trace
        assert out.read_bytes().startswith(b"%PDF-")
    finally:
        browser.close()
        driver.stop()
