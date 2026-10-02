"""Every path that presses something for a document follows the same rules.

A second review of the #36 repair found three more ways to save the wrong
document and a handful of smaller ones, each reproduced in a real browser.

The row link step ran first and judged a row by its links alone. A View or
a Download drawn as a button, a role=button element, a pointer span or an
input button went unseen, so a lone "Privacy Notice" link passed for the
document's own link under another name.

The row walk counted an element as the document's name when its own text
nodes were the title, whatever its children added, so a link reading the
title with "Privacy Notice" in a span inside it was pressed as the name.

The page's bulk Download button, which hands over every ticked document,
was taken by the one control step as "the one control of the date", since
the nearest element printing a date around it was the whole page, and it
was pressed without any of the checks the box and Download path makes.

Smaller ones. The page's Download could be another row's own button. A
control was found again by its place on the page when it was pressed, so a
list that changed in between moved the press. A redirect of a request made
before the attempt passed for an answer to this one. Nothing refused a
control that signs out.

Everything here is invented. Every test goes through download_bill, the
way a run does, in a real browser, and each page records where every click
truly landed, in the capture phase before any handler runs.
"""
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import etrade_site as site

ACCOUNT = "Invented Brokerage - 4242"
BROKERAGE = "Brokerage Statement"
RETIREMENT = "Retirement Statement"
ALONE = "2025-10-31"
EARLIER = "2025-09-30"

LISTENER = ("<script>window.hits = [];"
            "document.addEventListener('click', e => { const g = e.target.closest('[data-guid]');"
            " window.hits.push(g ? g.dataset.guid : e.target.tagName.toLowerCase());"
            " if (!g || g.tagName.toLowerCase() !== 'input') e.preventDefault(); }, true);</script>")

# The page's own Download, which hands over whichever boxes are ticked.
DOWNLOAD = ("<button type='button' data-guid='download' onclick=\"window.handed = Array.from("
            "document.querySelectorAll('input:checked')).map(b => b.dataset.guid).join(',') || 'nothing'\">"
            "%s</button>")


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        b = driver.chromium.launch(headless=True)
    except Exception as e:                       # no browser on this machine
        pytest.skip("no browser to drive: %s" % e)
    yield b
    b.close()
    driver.stop()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def nothing_listed(monkeypatch):
    """Each test says what the lists the page loaded held."""
    monkeypatch.setattr(site, "_LISTED", {})
    monkeypatch.setattr(site, "_LISTED_TITLES", {})
    monkeypatch.setattr(site, "goto_documents", lambda pg: True)
    monkeypatch.setattr(site, "expand_all", lambda pg: None)


def _listed(monkeypatch, listed):
    """`listed` maps each date to the titles the lists held on it."""
    monkeypatch.setattr(site, "_LISTED", {iso: len(t) for iso, t in listed.items()})
    monkeypatch.setattr(site, "_LISTED_TITLES", {iso: set(t) for iso, t in listed.items()})


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Stands in for the catch. It presses the element the way the real
    catch does, a click on its middle, and remembers where the press
    landed. A press that lands on a guid in `brings` hands over that
    guid's PDF, written where the download asked for it."""
    hits: list = []
    brings: set = set()

    def fake(pg, el, label, out_path, trace=None, dl_dir=None):
        before = len(pg.evaluate("window.hits"))
        try:
            el.click(timeout=3000)
        except Exception as e:
            hits.append("click failed " + type(e).__name__)
            return False
        pg.wait_for_timeout(50)
        landed = pg.evaluate("window.hits")[before:]
        hits.extend(landed)
        handed = [h for h in landed if h in brings]
        if handed:
            Path(out_path).write_bytes(b"%PDF-1.4\n% invented " + handed[0].encode() + b"\n%%EOF\n")
            return True
        return False
    monkeypatch.setattr(site, "_catch_pdf", fake)

    def download(page, iso, title=BROKERAGE):
        out = tmp_path / "Statements" / "document.pdf"
        if out.exists():
            out.unlink()
        trace: list = []
        got = site.download_bill(page, tmp_path / "dl", iso, out, title, trace)
        return got, (out.read_bytes() if out.exists() else b""), trace
    return hits, brings, download


def _says_nothing_the_page_said(trace):
    text = json.dumps(trace)
    for leaked in ("Brokerage", "Privacy", "Notice", "Invented", "4242", "g-"):
        assert leaked not in text, (leaked, text)


# --- the row link step sees every control in the row -----------------------

OWN = {
    "button View": "<button type='button' data-guid='g-view'>View</button>",
    "role=button Download": "<div role='button' tabindex='0' data-guid='g-view'>Download</div>",
    "pointer span View": "<span data-guid='g-view' style='cursor:pointer'>View</span>",
    "input button Download": "<input type='button' value='Download' data-guid='g-view'>",
}


@pytest.mark.parametrize("own", list(OWN), ids=list(OWN))
def test_a_lone_notice_link_beside_a_view_that_is_not_a_link_is_never_pressed(page, run, monkeypatch, own):
    """His row shape, the date, the account, the document's own View or
    Download drawn as something other than a link, and a notice link. The
    row link step looked at links only, took the notice as the document's
    own link under another name, and saved it (review, P1)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-notice'>Privacy Notice</a></td></tr></tbody></table>%s"
                     % (ACCOUNT, OWN[own], LISTENER))
    hits, brings, download = run
    brings.update({"g-view", "g-notice"})
    got, saved, trace = download(page, ALONE)
    assert "g-notice" not in hits, (hits, saved)
    assert got and b"invented g-view\n" in saved and hits == ["g-view"], (hits, saved)
    _says_nothing_the_page_said(trace)


def test_an_input_button_download_in_a_list_row_is_seen_by_the_row_walk(page, run, monkeypatch):
    """A list row, so the row link step is not involved, the document's
    Download drawn as an input button. Neither the row walk nor the one
    control rule counted it, so the notice was the row's only control and
    was pressed (review, P1e)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<ul><li><span>10/31/25</span> <span>%s</span> "
                     "<input type='button' value='Download' data-guid='g-view'> "
                     "<a href='#' data-guid='g-notice'>Privacy Notice</a></li></ul>%s" % (ACCOUNT, LISTENER))
    hits, brings, download = run
    brings.update({"g-view", "g-notice"})
    got, saved, trace = download(page, ALONE)
    assert "g-notice" not in hits, (hits, saved)
    assert got and b"invented g-view\n" in saved and hits == ["g-view"], (hits, saved)


def test_a_notice_link_beside_a_button_under_another_name_is_never_pressed(page, run, monkeypatch):
    """The row holds a button that says something else as well, so either
    could be the document's. Neither is pressed."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<table><tbody><tr><td>10/31/25</td><td>%s</td>"
                     "<td><button type='button' data-guid='g-view'>Invented Monthly Report</button></td>"
                     "<td><a href='#' data-guid='g-notice'>Privacy Notice</a></td></tr></tbody></table>%s"
                     % (ACCOUNT, LISTENER))
    hits, brings, download = run
    brings.update({"g-view", "g-notice"})
    got, saved, trace = download(page, ALONE)
    assert hits == [] and not got and saved == b"", (hits, saved)
    _says_nothing_the_page_said(trace)


# --- a name is the element's whole words ----------------------------------

NAMED_BY_ITS_OWN_TEXT = {
    "run-on in a span": "<a href='#' data-guid='g-notice'>%s <span>PDF Privacy Notice</span></a>" % BROKERAGE,
    "subtitle in a small": "<a href='#' data-guid='g-notice'>%s<br><small>Annual Privacy Notice</small></a>"
                           % BROKERAGE,
}


@pytest.mark.parametrize("link", list(NAMED_BY_ITS_OWN_TEXT), ids=list(NAMED_BY_ITS_OWN_TEXT))
def test_a_notice_link_whose_own_text_is_the_title_is_not_the_name(page, run, monkeypatch, link):
    """The link's own text nodes are the title and a child adds the rest.
    It counted as the document's name and was pressed (review, P2)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<ul><li><span>10/31/25</span> <span data-guid='g-title'>%s</span> %s</li></ul>%s"
                     % (BROKERAGE, NAMED_BY_ITS_OWN_TEXT[link], LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, saved, trace = download(page, ALONE)
    assert "g-notice" not in hits, (hits, saved)
    assert hits == ["g-title"] and not got, (hits, saved)
    _says_nothing_the_page_said(trace)


def test_his_table_row_with_such_a_notice_link_presses_nothing(page, run, monkeypatch):
    """His row shape with a box and such a notice link, and no Download
    button on the page. The row walk pressed the notice as the title
    (review, P2c)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<table><tbody><tr><td><input type='checkbox' data-guid='g-box'></td>"
                     "<td>10/31/25</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-notice'>%s <span>Privacy Notice</span></a></td>"
                     "</tr></tbody></table>%s" % (ACCOUNT, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-notice")
    got, saved, trace = download(page, ALONE)
    assert hits == [] and not got, (hits, saved)
    assert page.evaluate("document.querySelector('[data-guid=g-box]').checked") is False


# --- the page's Download goes through the box path only --------------------

TWO_ROWS = ("<table><tbody>"
            "<tr><td><input type='checkbox' data-guid='g-notice-box'%s></td><td>10/31/25</td>"
            "<td><a href='#' data-guid='g-notice'>Privacy Notice</a></td></tr>"
            "<tr><td><input type='checkbox' data-guid='g-mine-box'></td><td>10/31/25</td>"
            "<td><a href='#' data-guid='g-mine'>" + BROKERAGE + "</a></td></tr>"
            "</tbody></table>")


@pytest.mark.parametrize("left_ticked, words", [(False, "Download"), (True, "Download"), (False, "Download PDF")],
                         ids=["nothing ticked", "a notice left ticked", "a bulk Download PDF"])
def test_the_pages_download_button_is_never_the_one_control_of_the_date(page, run, monkeypatch,
                                                                       left_ticked, words):
    """The page's bulk Download was "the one control of the date", since
    the nearest element printing a date around it was the page, and it was
    pressed with nothing ticked, or with a notice's box left ticked, and
    whatever it handed over was saved under this document's name (review,
    P6). It is pressed only through the box path, with this row's own box
    the only one ticked, and a bulk button worded otherwise not at all."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content((TWO_ROWS % (" checked" if left_ticked else "")) + (DOWNLOAD % words) + LISTENER)
    hits, brings, download = run
    brings.add("download")
    got, saved, trace = download(page, ALONE)
    handed = page.evaluate("window.handed || ''")
    refusals = [(t["way"], t["why"]) for t in trace if t.get("note", "").startswith("not sure which")]
    if left_ticked or words != "Download":
        assert "download" not in hits and not got, (hits, handed, refusals)
    else:
        assert handed == "g-mine-box" and got, (hits, handed, refusals)
        assert hits[-1] == "download" and hits.count("download") == 1, hits
    assert not page.evaluate("document.querySelector('[data-guid=g-mine-box]').checked")
    if words != "Download":
        assert ("control", "the control sits outside any one row") in refusals, refusals


def test_the_pages_download_button_must_sit_outside_every_row(page, run, monkeypatch):
    """The only visible button named Download was another row's own, and it
    was pressed after this row's box was ticked (review, P8)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE], EARLIER: [BROKERAGE]})
    page.set_content("<table><tbody>"
                     "<tr><td><input type='checkbox' data-guid='g-mine-box'></td><td>10/31/25</td>"
                     "<td><span data-guid='g-title'>%s</span></td><td></td></tr>"
                     "<tr><td><input type='checkbox' data-guid='g-other-box'></td><td>09/30/25</td>"
                     "<td><span>%s</span></td>"
                     "<td><button type='button' data-guid='g-other-download'>Download</button></td></tr>"
                     "</tbody></table>%s" % (BROKERAGE, BROKERAGE, LISTENER))
    hits, brings, download = run
    brings.add("g-other-download")
    got, saved, trace = download(page, ALONE)
    assert "g-other-download" not in hits and not got, (hits, saved)
    assert {"note": "the only Download buttons sit inside rows, so none was pressed", "in_rows": 1} in trace
    assert not page.evaluate("document.querySelector('[data-guid=g-mine-box]').checked")


# --- the control pressed is the one that was checked -----------------------

def test_the_one_control_pressed_is_the_one_that_was_checked(page, run, monkeypatch):
    """The control was handed back as "the i-th control named like a
    document" and found again at the press. A row added above it in
    between, a late list or a lazy load, moved the press onto the other
    document (review, P9)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<div id='rows'><div class='doc'><span>10/31/25</span> "
                     "<a href='#' data-guid='g-mine'>%s PDF</a></div></div>%s" % (BROKERAGE, LISTENER))
    real_around = site._around

    def around_then_the_list_changes(el, title):
        got = real_around(el, title)
        page.evaluate("""() => { const d = document.createElement('div'); d.className = 'doc';
            d.innerHTML = "<span>09/30/25</span> <a href='#' data-guid='g-other'>Retirement Statement PDF</a>";
            document.getElementById('rows').prepend(d); }""")
        return got
    monkeypatch.setattr(site, "_around", around_then_the_list_changes)
    monkeypatch.setattr(site, "_row_link_for", lambda *a, **k: (None, ""))
    hits, brings, download = run
    brings.update({"g-mine", "g-other"})
    got, saved, _trace = download(page, ALONE)
    assert hits == ["g-mine"] and b"invented g-mine\n" in saved, (hits, saved)


def test_the_row_link_pressed_is_the_one_that_was_checked(page, run, monkeypatch):
    """The same in the row link step. A row of the same date whose link
    carries the same name arrives above his row after the check, and the
    press followed the new first row."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<table><tbody id='rows'><tr><td>10/31/25</td><td>%s</td>"
                     "<td><a href='#' data-guid='g-mine' aria-label='%s PDF for %s'>%s</a></td></tr>"
                     "</tbody></table>%s" % (ACCOUNT, BROKERAGE, ACCOUNT, BROKERAGE, LISTENER))
    real_around = site._around
    moved = []

    def around_then_the_list_changes(el, title):
        got = real_around(el, title)
        if not moved:
            moved.append(1)
            page.evaluate("""() => { const r = document.createElement('tr');
                r.innerHTML = "<td>10/31/25</td><td>Invented Other - 9999</td>" +
                  "<td><a href='#' data-guid='g-other' aria-label='Brokerage Statement PDF for Invented Other'>" +
                  "Brokerage Statement</a></td>";
                document.getElementById('rows').prepend(r); }""")
        return got
    monkeypatch.setattr(site, "_around", around_then_the_list_changes)
    hits, brings, download = run
    brings.update({"g-mine", "g-other"})
    got, saved, _trace = download(page, ALONE)
    assert hits == ["g-mine"] and b"invented g-mine\n" in saved, (hits, saved)


# --- a redirect of an earlier request is not this document's answer --------

class _Server:
    """A local server whose page asks for an earlier document as it loads
    and holds that answer until it is told to send a redirect. The press
    asks for this document after a moment."""

    PAGE = ("<!doctype html><html><body><table><tbody><tr><td>10/31/25</td>"
            "<td><a id='doc' href='#' aria-label='%s PDF for %s' onclick=\"event.preventDefault();"
            "setTimeout(() => fetch('/docs/this.pdf'), 1500)\">%s</a></td></tr></tbody></table>"
            "<script>fetch('/docs/earlier')</script></body></html>" % (BROKERAGE, ACCOUNT, BROKERAGE)).encode()

    def __init__(self):
        self.release = threading.Event()
        release, page = self.release, self.PAGE

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/docs/earlier":
                    release.wait(30)
                    self.send_response(302)
                    self.send_header("Location", "/docs/earlier-file.pdf")
                    self.end_headers()
                    return
                if self.path.endswith(".pdf"):
                    body = b"%PDF-1.4\n% invented " + (b"earlier" if "earlier" in self.path else b"this") \
                        + b"\n%%EOF\n"
                    content = "application/pdf"
                else:
                    body, content = page, "text/html"
                self.send_response(200)
                self.send_header("Content-Type", content)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        self.server = Threaded(("127.0.0.1", 0), Handler)
        self.base = "http://127.0.0.1:%d/" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()


def test_a_redirect_of_an_earlier_request_is_not_this_documents_pdf(browser, monkeypatch, tmp_path):
    """A request made before this attempt, the last document's, is answered
    during it with a redirect, and the redirect's PDF passed for an answer
    to this document's press, since the redirect is a new request (review).
    The request a redirect came from is what is checked now."""
    srv = _Server()
    monkeypatch.setattr(site, "is_safe_url", lambda u: (u or "").startswith(srv.base))
    real_take = site._take_new_pdf

    def late(dl_dir, seen, out_path, **how):
        srv.release.set()                        # the earlier redirect arrives during the attempt
        return real_take(dl_dir, seen, out_path, **how)
    monkeypatch.setattr(site, "_take_new_pdf", late)
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    pg = browser.new_page()
    try:
        pg.goto(srv.base + "page")
        pg.wait_for_timeout(500)
        out = tmp_path / "out.pdf"
        trace: list = []
        assert site.download_bill(pg, tmp_path / "dl", ALONE, out, BROKERAGE, trace), trace
        assert b"invented this" in out.read_bytes(), out.read_bytes()
        assert {"note": "a PDF answering an earlier request was left alone", "type": "pdf"} in trace, trace
    finally:
        pg.close()
        srv.close()


# --- nothing that signs out is ever pressed ---------------------------------

@pytest.mark.parametrize("words", ["Sign out", "Log off", "Log out", "Signout"])
@pytest.mark.parametrize("shape", ["tr", "li"])
def test_a_control_that_signs_out_is_never_pressed(page, run, monkeypatch, words, shape):
    """The only control of a row that prints no title may be the
    document's own link under another name, and nothing refused one that
    signs out (review)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    if shape == "tr":
        row = ("<table><tbody><tr><td>10/31/25</td><td>%s</td>"
               "<td><a href='#' data-guid='g-out'>%s</a></td></tr></tbody></table>" % (ACCOUNT, words))
    else:
        row = ("<ul><li><span>10/31/25</span> <span>%s</span> "
               "<span data-guid='g-out' style='cursor:pointer'>%s</span></li></ul>" % (ACCOUNT, words))
    page.set_content(row + LISTENER)
    hits, brings, download = run
    brings.add("g-out")
    got, saved, _trace = download(page, ALONE)
    assert hits == [] and not got, (hits, saved)
    assert not site.is_safe_control(words) and not site._guard_allows((words,), BROKERAGE)


@pytest.mark.parametrize("words", ["Freeze account", "Invite a friend"])
def test_the_row_walk_presses_only_what_looks_like_a_document_action(page, run, monkeypatch, words):
    """Every other step pressed a control only when is_safe_control let it,
    which asks that it look like a document action. The row walk asked only
    that it pass the guard, so the one control of a row that prints no
    title, whatever it said short of the guard's words, was pressed as the
    document's own link under another name (review)."""
    _listed(monkeypatch, {ALONE: [BROKERAGE]})
    page.set_content("<ul><li><span>10/31/25</span> <span>%s</span> "
                     "<span data-guid='g-other' style='cursor:pointer'>%s</span></li></ul>%s"
                     % (ACCOUNT, words, LISTENER))
    hits, brings, download = run
    brings.add("g-other")
    got, saved, trace = download(page, ALONE)
    assert hits == [] and not got, (hits, saved)
    row = next(t for t in trace if t.get("note") == "the document's row")
    assert [c["left_out"] for c in row["candidates"]] == [True], row
