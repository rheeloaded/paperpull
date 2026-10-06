"""card.apple.com as the first recording showed it, made up but the same shape.

The tester's Record and Diagnose (#52, round one) showed a page that draws
each section itself. An address typed in for a section answers 404, and
only the front page and /savings answer at all. After a fresh load the
page stayed blank for several seconds before its menu appeared. The card's
statements are the menu's Statements. The Savings statements and the tax
forms are under the menu's Savings, then Documents, then a link carrying
its count. Every document on all three lists is one icon button named
"Download statement of <month> <year> (PDF)", a tax form's included, and
pressing it downloads the PDF under a name Apple gives it.

Everything below is invented, the months, the years, the counts, the name
and the links. What it keeps from the recording is the shape. The menu is
a nav with links, the lists are inside main, the Savings pages keep the
address /savings, the buttons are custom elements with a role and a name
and only an icon to show, the menu's own Statements link stays on screen on
the Savings Documents page, where pressing it would open the card's, the
Savings statements list carries a link back to Documents, and a download
is named "Apple Card Statement - <month> <year>.pdf", "Savings Statement -
<month> <year>.pdf" or "1099-INT <year> - Tax Form.pdf".

The knobs are for what nobody has seen and a page like this could do.
late moves the address to the front page as soon as the menu's Statements
is pressed on a Savings list, and draws the card's list that long after.
mode says what is on screen meanwhile. "" leaves the Savings list as it
was, "redraw" draws it again on new elements, and "reuse" keeps the very
same buttons and relabels them as the card's when the time is up.
"misroute" opens the Savings statements when Tax Documents is pressed.
"misname" names each tax form's file for the year before its button's.
stray puts a control named with PDF that is not a document on the Savings
pages, the card's list or the Documents page, next to a year or a month,
a link on the first and the last and a button on the card's. list_late
draws a Savings list that long after its link is pressed. narrow draws the
menu inside the page's content. overlay lays a promo over the front page.
folder hands each download to the test to save into a folder, the way a
real Edge or Chrome saves it, instead of raising a download event. deaf
lets the first press on each list it draws do nothing, the way the first
Pilot saw it (#52, 0.37.1), reacts has that press put up a control of its
own instead, and dead lets no press do anything. The page counts every
press on a document's button and every download it starts.
"""
import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import applecard_site as site


APP = r"""<!doctype html>
<html><head><title>Apple Card</title></head>
<body style="overflow:hidden"><div id="root"><div class="shell"><ui-app></ui-app></div></div>
<div id="legal" hidden></div>
<script>
const K = __KNOBS__;
const CARD = [["March", "2031"], ["February", "2031"], ["January", "2031"], ["December", "2030"]];
const SAVINGS = [["March", "2031"], ["February", "2031"], ["January", "2031"]];
const TAX = K.tax_empty ? [] : [["January", "2030"], ["January", "2029"]];
let view = location.pathname.indexOf("/savings") === 0 ? "savings" : "home";
const app = document.querySelector("ui-app");
const legal = document.getElementById("legal");
window.pressed = [];
window.presses = 0;
window.downloads = 0;
// Whether the list on screen was drawn since the last press on a document.
let fresh = false;

function menu() {
  const link = (href, words) => '<li class="item"><a class="m" tabindex="0" href="' + href +
    '"><span aria-hidden="true"><svg width="8" height="8"></svg></span><div class="t">' + words + '</div></a></li>';
  return '<div class="bar"><div class="brand"></div><div class="who"><ul><li><a class="me" href="#">' +
    'Dana Quill</a></li></ul></div><nav class="menu"><ul>' +
    link("/", "Payments") + link("/installments", "Installments") + link("/statements", "Statements") +
    link("/settings", "Settings") + link("/savings", "Savings") + link("/support", "Support") +
    '</ul></nav></div>';
}

function rows(list) {
  const years = [];
  for (const r of list) { if (!years.includes(r[1])) years.push(r[1]); }
  return years.map((y) => '<section class="year"><span class="sr" style="display:none">' + y +
    '</span><div class="list"><ul>' + list.filter((r) => r[1] === y).map((r) =>
      '<li class="row"><div class="cell"><div class="when"><div>' + r[0] + '</div><div></div></div>' +
      '<div aria-live="polite" class="act"><ui-button role="button" tabindex="0" class="dl" ' +
      'aria-label="Download statement of ' + r[0] + ' ' + y + ' (PDF)" data-m="' + r[0] +
      '" data-y="' + y + '"><button tabindex="-1" type="button" style="display:none"></button>' +
      '<svg width="16" height="16"><rect width="16" height="16"></rect></svg></ui-button></div></div></li>'
    ).join("") + '</ul></div></section>').join("");
}

function count(words, n, to) {
  return '<li class="entry"><a class="go" tabindex="0" href="#" data-to="' + to + '"><div><div><p>' +
    words + '</p></div><div><span><span>' + n + '</span><svg width="8" height="8"></svg></span></div></div></a></li>';
}

function back() {
  return '<div class="head"><div><a class="back" aria-current="page" tabindex="0" href="#" data-to="documents">' +
    '<svg aria-hidden="true" width="8" height="8"></svg>Documents</a></div></div>';
}

function stray(words, near, asButton) {
  const control = asButton
    ? '<button type="button" class="doc" aria-label="' + words + ' (PDF)">' + words + '</button>'
    : '<a class="doc" href="https://www.example.com/terms.pdf" aria-label="' + words + ' (PDF)">' + words + '</a>';
  return '<div class="fine">' + control + '<p>' + near + '</p></div>';
}

function overlay() {
  return '<div class="promo" role="dialog"><button class="x" aria-label="Close Apple Card Account">' +
    '<svg width="8" height="8"></svg></button><button class="x">Close</button></div>';
}

function page(inner) {
  const bar = menu();
  return (K.narrow ? '' : bar) + '<div class="content"><main>' + (K.narrow ? bar : '') +
    '<div class="page">' + inner +
    '<footer role="contentinfo" class="foot"><a href="https://www.apple.com/legal/">Legal</a></footer></div></main></div>';
}

const VIEWS = {
  home: () => page('<h2>Payments</h2><button>Balance Details</button><button>Pay More</button>' +
    (K.overlay ? overlay() : '')),
  statements: () => page('<h2>Statements</h2><button>Export Transactions</button>' +
    (K.stray === "card" ? stray("Terms and Conditions", "Updated March 2031", true) : '') + rows(CARD)),
  savings: () => page('<h2>Savings</h2><section class="docs"><div>' +
    '<li class="entry"><a class="go" tabindex="0" href="/savings/documents" data-to="documents">' +
    '<div><div><p>Documents</p></div><div><svg aria-hidden="true" width="8" height="8"></svg></div></div></a></li>' +
    '</div></section><a href="/savings/routing" data-to="home">Routing &amp; Account Numbers</a>'),
  documents: () => page('<h2>Documents</h2>' +
    (K.stray === "documents" ? stray("Account Terms", "Read these before you save") : '') +
    '<section class="docs"><div>' +
    count("Statements", SAVINGS.length, "sav_statements") + count("Tax Documents", TAX.length, "tax") +
    '</div></section>'),
  sav_statements: () => page(back() + '<h2>Statements</h2>' + rows(SAVINGS)),
  tax: () => page(back() + '<h2>Tax Documents</h2>' + rows(TAX)),
};

function onSavings() { return location.pathname.indexOf("/savings") === 0; }

// A PDF link and a copyright year that stay put on every Savings page,
// outside the part of the page each press draws again.
function syncLegal() {
  if (K.stray !== "savings") return;
  if (!legal.firstChild) legal.innerHTML = stray("Savings Terms and Conditions", "Copyright 2031 Example Bank");
  legal.hidden = !onSavings();
}

function show(v, url) {
  view = v;
  fresh = true;
  if (url) history.replaceState(null, "", url);
  app.innerHTML = VIEWS[v]();
  syncLegal();
}

function relabel() {
  view = "statements";
  Array.from(document.querySelectorAll("ui-button")).forEach((b, i) => {
    const r = CARD[i];
    if (!r) { b.remove(); return; }
    b.setAttribute("aria-label", "Download statement of " + r[0] + " " + r[1] + " (PDF)");
    b.dataset.m = r[0];
    b.dataset.y = r[1];
  });
  const head = document.querySelector("main .head");
  if (head) head.remove();
  document.querySelector("main h2").textContent = "Statements";
  syncLegal();
}

function fileName(from, m, y) {
  if (from === "tax") return "1099-INT " + (K.mode === "misname" ? String(Number(y) - 1) : y) + " - Tax Form.pdf";
  if (from === "savings") return "Savings Statement - " + m + " " + y + ".pdf";
  if (from === "card") return "Apple Card Statement - " + m + " " + y + ".pdf";
  return "Document.pdf";
}

function download(b) {
  window.downloads += 1;
  const from = { statements: "card", sav_statements: "savings", tax: "tax" }[view] || "other";
  const body = "%PDF-1.4\n% " + from + " " + b.dataset.m + " " + b.dataset.y + "\n" + "x".repeat(2500) + "\n%%EOF\n";
  const name = fileName(from, b.dataset.m, b.dataset.y);
  if (K.folder) { window.landInFolder(name, body); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], { type: "application/pdf" }));
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

document.addEventListener("click", (e) => {
  const x = e.target.closest(".promo button");
  if (x) { window.pressed.push(x.getAttribute("aria-label") || x.textContent); return; }
  const b = e.target.closest("ui-button");
  if (b) {
    window.presses += 1;
    const first = fresh;
    fresh = false;
    if (K.dead || ((K.deaf || K.reacts) && first)) {
      if (K.reacts) b.closest(".act").insertAdjacentHTML("beforeend", '<button type="button" class="note">Try again later</button>');
      return;
    }
    download(b);
    return;
  }
  const a = e.target.closest("a[href]");
  if (!a || !a.closest("ui-app")) return;
  const href = a.getAttribute("href");
  if (href.indexOf("http") === 0) return;
  e.preventDefault();
  if (a.dataset.to) {
    const to = K.mode === "misroute" && a.dataset.to === "tax" ? "sav_statements" : a.dataset.to;
    const url = onSavings() ? "/savings" : null;
    if (K.list_late && (to === "tax" || to === "sav_statements")) {
      setTimeout(() => show(to, url), K.list_late);
      return;
    }
    show(to, url);
    return;
  }
  if (href === "/statements") {
    const was = view;
    if (K.late && (was === "sav_statements" || was === "tax")) {
      history.replaceState(null, "", "/");
      syncLegal();
      if (K.mode === "reuse") { setTimeout(relabel, K.late); return; }
      if (K.mode === "redraw") app.innerHTML = VIEWS[was]();
      setTimeout(() => show("statements", null), K.late);
      return;
    }
    show("statements", K.stay && onSavings() ? null : "/");
    return;
  }
  if (href === "/savings") { show("savings", "/savings"); return; }
  show("home", "/");
});

setTimeout(() => show(view, null), K.draw_ms || 0);
</script></body></html>
"""


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """A made-up page redraws at once, so the waits after a press are cut
    short, and nothing here needs scrolling. The page is given 6 seconds
    to be the list a walk asked for, where the slowest redraw below takes
    1.5, and a download, which starts as soon as its button is pressed, a
    few seconds to land. Whichever list the last test opened is
    forgotten."""
    monkeypatch.setattr(site, "STEP_SETTLE_MS", 300, raising=False)
    monkeypatch.setattr(site, "ARRIVE_SECONDS", 6, raising=False)
    monkeypatch.setattr(site, "PRESS_WAIT_SECONDS", 3, raising=False)
    monkeypatch.setattr(site, "AGAIN_WAIT_SECONDS", 3, raising=False)
    monkeypatch.setattr(site, "LAST_WAIT_SECONDS", 1, raising=False)
    monkeypatch.setattr(site, "scroll_full_page", lambda *a, **k: None)
    monkeypatch.setattr(site, "BILLING_URL", site.BILLING_URL)
    getattr(site, "_ARRIVED", {}).clear()
    yield
    getattr(site, "_ARRIVED", {}).clear()


@pytest.fixture()
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        chromium = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    yield chromium
    chromium.close()
    driver.stop()


def _open(browser, draw_ms: int = 0, stay: bool = False, late: int = 0, mode: str = "", **knobs):
    """A page on the made-up site, and the list of every path loaded. No
    other host is ever reached."""
    served = []
    knobs.update(draw_ms=draw_ms, stay=stay, late=late, mode=mode)
    html = APP.replace("__KNOBS__", json.dumps(knobs))

    def serve(route, request):
        path = urlsplit(request.url).path
        served.append(path)
        if path in ("/", "/savings"):
            route.fulfill(status=200, content_type="text/html", body=html)
        else:
            route.fulfill(status=404, content_type="text/html", body="<html><body>Not Found</body></html>")

    ctx = browser.new_context(accept_downloads=True)
    ctx.route(lambda url: not url.startswith("https://card.apple.com/"), lambda route: route.abort())
    ctx.route("https://card.apple.com/**", serve)
    return ctx.new_page(), served


def test_each_list_is_reached_through_the_menu_the_way_the_recording_went(browser):
    page, served = _open(browser)
    page.goto("https://card.apple.com/")

    assert site.goto_section(page, site.CARD)
    card = site.collect_download_docs(page, site.CARD)
    assert [(d.kind, d.date_text) for d in card] == [
        ("card", "2031-03-31"), ("card", "2031-02-28"), ("card", "2031-01-31"), ("card", "2030-12-31")]
    assert card[0].title == "Apple Card Statement - March 2031"

    assert site.goto_section(page, site.SAVINGS)
    savings = site.collect_download_docs(page, site.SAVINGS)
    assert [(d.kind, d.date_text, d.title) for d in savings] == [
        ("savings", "2031-03-31", "Savings Statement - March 2031"),
        ("savings", "2031-02-28", "Savings Statement - February 2031"),
        ("savings", "2031-01-31", "Savings Statement - January 2031")]

    # A tax form's button names a month and never says tax, and the list
    # it is on is what makes it one.
    assert site.goto_section(page, site.TAX)
    tax = site.collect_download_docs(page, site.TAX)
    assert [(d.kind, d.date_text, d.title) for d in tax] == [
        ("tax", "2030-12-31", "Tax Document - 2030"), ("tax", "2029-12-31", "Tax Document - 2029")]

    # Walking the menu loaded nothing, so no section address was tried.
    assert served == ["/"]


def test_the_tax_list_is_read_although_its_buttons_never_say_tax(browser):
    """On the Tax Documents list the button names a month and a year and
    the row names only the month. The first build wanted the word tax or
    1099 before it would take a form, and so took none."""
    page, served = _open(browser)
    page.goto("https://card.apple.com/savings")
    page.wait_for_selector("nav a")
    page.evaluate("show('tax', '/savings')")
    tax = site.collect_download_docs(page, site.TAX)
    assert [(d.kind, d.date_text) for d in tax] == [("tax", "2030-12-31"), ("tax", "2029-12-31")]
    el, label = site._control_for(page, site.TAX, "2029-12-31")
    assert el is not None and label == "Download statement of January 2029 (PDF)"


def test_a_front_page_that_draws_late_is_waited_for(browser):
    """The tester's Diagnose found the page blank about five seconds after
    a fresh load, where the old fixed wait gave up, and drawn a few
    seconds later. The run starts on a 404, like the one that Diagnose
    ended up on."""
    page, served = _open(browser, draw_ms=6500)
    page.goto("https://card.apple.com/documents")
    assert site.goto_section(page, site.CARD)
    assert [d.date_text for d in site.collect_download_docs(page, site.CARD)][:1] == ["2031-03-31"]
    assert served == ["/documents", "/"]


def test_the_cards_statements_are_never_read_as_savings_at_a_savings_address(browser):
    """Nobody has seen whether the menu's Statements, pressed on a Savings
    page, keeps the Savings address. If it does, what it shows is still
    the card's, so it must never be read as Savings, and the card's list
    must still be reached."""
    page, served = _open(browser, stay=True)
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.SAVINGS)
    assert [d.date_text for d in site.collect_download_docs(page, site.SAVINGS)] == [
        "2031-03-31", "2031-02-28", "2031-01-31"]

    assert site.goto_section(page, site.CARD)
    assert urlsplit(page.url).path == "/"
    card = site.collect_download_docs(page, site.CARD)
    assert len(card) == 4 and {d.kind for d in card} == {"card"}


def test_each_kind_saves_the_pdf_from_its_own_list(browser, tmp_path):
    """The kinds come in the order a run takes them, newest first, so the
    page moves between the three lists and back. Each file must be the
    one its own list handed over."""
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    for n, (title, iso, want) in enumerate([
            ("Apple Card Statement - February 2031", "2031-02-28", b"card February 2031"),
            ("Savings Statement - February 2031", "2031-02-28", b"savings February 2031"),
            ("Tax Document - 2029", "2029-12-31", b"tax January 2029"),
            ("Savings Statement - March 2031", "2031-03-31", b"savings March 2031"),
            ("Apple Card Statement - December 2030", "2030-12-31", b"card December 2030")]):
        out = tmp_path / ("%d.pdf" % n)
        trace = []
        assert site.download_bill(page, None, iso, out, title=title, trace=trace), (title, trace)
        assert want in out.read_bytes(), title


def _savings_then_card(page, tmp_path):
    """A Savings statement and then the card's statement of the same
    month, the one move between lists that is a single press."""
    got = []
    for n, (title, iso) in enumerate([
            ("Savings Statement - February 2031", "2031-02-28"),
            ("Apple Card Statement - February 2031", "2031-02-28")]):
        out = tmp_path / ("%d.pdf" % n)
        trace = []
        assert site.download_bill(page, None, iso, out, title=title, trace=trace), (title, trace)
        got.append(out.read_bytes())
    return got


def test_a_savings_list_left_on_screen_is_never_read_as_the_cards(browser, tmp_path):
    """The menu's Statements, pressed on a Savings list, moves the address
    to the front page at once and draws the card's list 1.5 seconds later.
    Taken as soon as the address agreed, the Savings list still on screen
    was read as the card's, and its February was saved as the card's
    February, done for good. The buttons that were there before the press
    must be gone before the list is read."""
    page, served = _open(browser, late=1500)
    page.goto("https://card.apple.com/")
    savings, card = _savings_then_card(page, tmp_path)
    assert b"savings February 2031" in savings
    assert b"card February 2031" in card


def test_a_savings_list_drawn_again_after_the_address_moved_is_not_the_cards(browser, tmp_path):
    """The same move, on a page that draws the Savings list again, on new
    elements, while the card's list loads. Those buttons were not on screen
    before the press, so only the list's own content can tell. The Savings
    statements list carries its link back to Documents and the card's list
    has none."""
    page, served = _open(browser, late=1500, mode="redraw")
    page.goto("https://card.apple.com/")
    savings, card = _savings_then_card(page, tmp_path)
    assert b"savings February 2031" in savings
    assert b"card February 2031" in card


def test_the_same_buttons_relabeled_are_left_for_a_fresh_front_page(browser, tmp_path):
    """The same move, on a page that keeps the very buttons of the Savings
    list and relabels them as the card's 1.5 seconds later. Such a list can
    never be shown to be new, so it is not read, and the card's list is
    opened again from the front page, loaded fresh, which holds nothing
    from before."""
    page, served = _open(browser, late=1500, mode="reuse")
    page.goto("https://card.apple.com/")
    savings, card = _savings_then_card(page, tmp_path)
    assert b"savings February 2031" in savings
    assert b"card February 2031" in card
    assert served == ["/", "/"]


def test_a_list_with_more_documents_than_its_link_counted_is_not_read(browser, tmp_path):
    """Tax Documents pressed, and the Savings statements drawn instead. The
    link said 2 and the list holds 3, so it is not the tax forms, and none
    of its statements may be read or saved as one."""
    page, served = _open(browser, mode="misroute")
    page.goto("https://card.apple.com/")
    # Each of its three buttons names a month of 2031, so read as tax
    # forms they would all be the form for 2031.
    trace = []
    out = tmp_path / "tax.pdf"
    assert not site.download_bill(page, None, "2031-12-31", out, title="Tax Document - 2031", trace=trace)
    assert not out.exists()
    refused = [t for t in trace if t.get("note") == "the list on screen was not taken"]
    assert len(refused) == 2, trace
    assert refused[-1]["within_its_count"] is False
    assert refused[-1]["documents_drawn"] and refused[-1]["address_agrees"]
    # the lists that were not sent astray still open
    assert site.goto_section(page, site.SAVINGS)
    assert len(site.collect_download_docs(page, site.SAVINGS)) == 3


def test_the_survey_comes_back_to_the_front_page_and_never_leaves_the_site(browser):
    """The page replaces its own history entry when a section opens, so
    going back after the survey followed Savings left card.apple.com. In
    the first Diagnose (#52) it landed on a 404, and every row read after
    the survey was read there."""
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.CARD)
    report = site.survey(page, dwell_ms=300)
    followed = [p.get("followed_from") for p in report["pages"]]
    assert "Savings" in followed, followed
    assert site.is_safe_url(page.url), page.url
    assert urlsplit(page.url).path == "/"
    assert page.locator("nav").get_by_role("link", name="Savings").is_visible()
    assert served == ["/", "/"]
    # and a section opens from there as usual
    assert site.goto_section(page, site.SAVINGS)


def test_the_fallback_census_counts_the_recorded_download_buttons(browser):
    """A failure file counts the page's download controls with this
    selector. The recorded ones are role=button with an aria-label and
    no text, and the old selector counted none of them, so a failure on
    the right list would have said there were no download controls."""
    from paperpull_core import failure
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.CARD)
    entry = next(e for e in failure.census(page, site.FALLBACK) if e.get("name") == "download_control")
    assert entry["matched"] == 4, entry
    assert entry["visible"] == 4, entry


def _app(page, tmp_path):
    """The orchestrator with only what these tests need, on a page of the
    made-up site."""
    import applecard_docs
    from paperpull_core import doc_types
    from storage import JsonStore
    app = applecard_docs.App.__new__(applecard_docs.App)
    app.args = SimpleNamespace(start_date=None, end_date=None, type=None, year=None, max_docs=None,
                               redownload=False, dry_run=False)
    app.config = {"owner": "", "document_types": ["Statement", "Tax Document"],
                  "max_path_length": 240, "min_pdf_bytes": 2000}
    app.rules = doc_types.load_rules()
    app.stats = {"mode": "discover", "skipped_out_of_scope": 0, "discovered": 0,
                 "manual_review": 0, "duplicate_filenames": 0}
    app.paths = SimpleNamespace(diagnostics=tmp_path)
    app.discovery = JsonStore(tmp_path / "discovery.json")
    app._context, app._work_page = object(), page
    return app


def test_the_diagnose_file_carries_no_row_text_and_no_dates(browser, tmp_path, monkeypatch, capsys):
    """Once Diagnose reaches a list, the loose row scrape reads a signed-in
    page. What it wrote was the row's text with digit runs masked, which
    passes a name straight through, and the first tester attached this
    file to a public issue. The rows are now flags and a category, the
    documents are counts, every word of the file goes through the fixed
    word list on its way out, and Diagnose says so."""
    import applecard_docs
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    # the survey has its own test, and here the rows are read where the
    # sections left the page
    monkeypatch.setattr(site, "survey", lambda *a, **k: {"pages": [], "responses": []})
    app = _app(page, tmp_path)
    app.stats = {"mode": ""}
    app.cmd_diagnose()
    said = capsys.readouterr().out

    text = (tmp_path / "diagnose-documents.json").read_text(encoding="utf-8")
    info = json.loads(text)
    assert info["documents_page_found"] is True
    assert info["rows_collected"] > 0
    assert "Dana" not in text and "Quill" not in text
    assert "2031-" not in text and "2030-" not in text and "March" not in text
    assert info["documents_recognized"]["by_kind"] == {"card": 4, "savings": 3, "tax": 2}
    for s in info["samples"]:
        assert set(s) == set(applecard_docs._SAMPLE_FIELDS), s
    assert "not on PaperPull's fixed list" in said
    assert "survey-" in said
    assert "attach it to the Apple Card issue" not in said


# -- round two ----------------------------------------------------------------


def test_a_pdf_link_on_every_savings_page_is_never_a_tax_form(browser):
    """The tester's own Diagnose found a control on the Savings page that
    holds no document and whose name the wider pattern took for a
    document's. Here one, named with PDF, sits on every Savings page, the
    tax list's included, beside a copyright year. The first
    build read every such control on the tax list as a tax form and took
    a lone year near it for the form's, which would have made it the
    newest document of all, in every Pilot. It is not a document, it is
    never pressed, and since it never goes away it must not make each new
    Savings list look like the one before it either."""
    page, served = _open(browser, stray="savings")
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.SAVINGS)
    assert len(site.collect_download_docs(page, site.SAVINGS)) == 3

    assert site.goto_section(page, site.TAX)
    trace = []
    tax = site.collect_download_docs(page, site.TAX, trace)
    assert [(d.kind, d.date_text) for d in tax] == [("tax", "2030-12-31"), ("tax", "2029-12-31")]
    assert trace[-1]["controls_of_another_shape"] == 1
    assert site._control_for(page, site.TAX, "2031-12-31") == (None, "")
    # Savings to tax without a fresh front page, the link was not taken
    # for a list left over
    assert served == ["/"]


def test_a_pdf_button_beside_the_cards_statements_is_never_one_of_them(browser, tmp_path):
    """A button for the card's terms, named with PDF, above the list, next
    to the month they were updated. Read by the words around it, it was
    the March statement, it came first on the page, and it was the one
    pressed."""
    page, served = _open(browser, stray="card")
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.CARD)
    assert [d.date_text for d in site.collect_download_docs(page, site.CARD)] == [
        "2031-03-31", "2031-02-28", "2031-01-31", "2030-12-31"]
    assert site._control_for(page, site.CARD, "2031-03-31")[1] == "Download statement of March 2031 (PDF)"
    out = tmp_path / "march.pdf"
    trace = []
    assert site.download_bill(page, None, "2031-03-31", out, title="Apple Card Statement - March 2031",
                              trace=trace), trace
    assert b"card March 2031" in out.read_bytes()


def test_a_list_drawn_late_is_waited_for_past_a_pdf_link_on_the_documents_page(browser, tmp_path):
    """Tax Documents pressed, and the Documents page stays on screen for a
    moment, with a PDF link of its own. Counted as a document control, it
    made the list look drawn, and the list was read before it was there."""
    page, served = _open(browser, stray="documents", list_late=1500)
    page.goto("https://card.apple.com/")
    out = tmp_path / "tax.pdf"
    trace = []
    assert site.download_bill(page, None, "2029-12-31", out, title="Tax Document - 2029", trace=trace), trace
    assert b"tax January 2029" in out.read_bytes()
    assert served == ["/"]


def test_the_menus_statements_drawn_inside_the_page_is_never_the_savings_list(browser, tmp_path):
    """A narrow window might draw the menu inside the page's content. If
    the menu's Statements then kept the Savings address, a Statements link
    without a count, found in the content, opened the card's list at a
    Savings address and every card statement was read as Savings. Both
    links the tester pressed for Savings carried a count."""
    page, served = _open(browser, stay=True, narrow=True)
    page.goto("https://card.apple.com/savings")
    page.wait_for_selector("nav a")
    assert site.goto_section(page, site.SAVINGS)
    assert [(d.kind, d.date_text) for d in site.collect_download_docs(page, site.SAVINGS)] == [
        ("savings", "2031-03-31"), ("savings", "2031-02-28"), ("savings", "2031-01-31")]
    out = tmp_path / "feb.pdf"
    assert site.download_bill(page, None, "2031-02-28", out, title="Savings Statement - February 2031")
    assert b"savings February 2031" in out.read_bytes()


def test_a_list_whose_link_counts_none_is_neither_waited_for_nor_a_failure(browser, tmp_path):
    """A Savings account with no tax forms yet. The link says 0, so there
    is nothing to wait for, no reason to load the front page again, and
    nothing for discovery to report as a list it refused."""
    page, served = _open(browser, tax_empty=True)
    page.goto("https://card.apple.com/")
    trace = []
    assert not site.goto_section(page, site.TAX, trace)
    notes = [t.get("note") for t in trace]
    assert "the list's link counted none" in notes, trace
    assert "the list on screen was not taken" not in notes, trace
    assert served == ["/"]

    app = _app(page, tmp_path)
    app.cmd_discover(quiet=True)
    assert not list(tmp_path.glob("failure-*.json"))
    kinds = sorted(v["title"].split(" - ")[0] for v in app.discovery.data.values())
    assert kinds == ["Apple Card Statement"] * 4 + ["Savings Statement"] * 3


def test_a_list_refused_during_discovery_writes_which_check_refused_it(browser, tmp_path):
    """Discovery is where a list the checks refuse is first met, on every
    Pilot and every full run. It used to leave no trace of it, only a line
    in the log that the section was not found, and the tax forms are not
    in a Pilot to be missed. It writes the failure file, which says which
    list and which check, as flags."""
    page, served = _open(browser, mode="misroute")
    page.goto("https://card.apple.com/")
    app = _app(page, tmp_path)
    app.cmd_discover(quiet=True)
    files = list(tmp_path.glob("failure-*.json"))
    assert len(files) == 1, files
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["step"] == "open a statements section"
    assert report["reason"] == "a list did not pass its checks"
    assert report["extra"]["postmortem"]["refused"] == [{
        "kind": "tax", "documents_drawn": True, "earlier_list_gone": True, "address_agrees": True,
        "no_savings_back_link": True, "within_its_count": False}]
    # the card's and the Savings statements were still discovered
    assert len(app.discovery.data) == 7


def test_a_row_that_arrives_between_reading_and_pressing_does_not_move_the_press(browser):
    """The button chosen for February was found again at press time by
    where it sat in the list. A statement that appeared at the top in the
    meantime would have moved the press onto March. It is found by its own
    name instead."""
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    assert site.goto_section(page, site.CARD)
    el, label = site._control_for(page, site.CARD, "2031-02-28")
    assert label == "Download statement of February 2031 (PDF)"
    page.evaluate("""() => {
      const ul = document.querySelector('main section.year ul');
      const li = document.createElement('li');
      li.innerHTML = '<ui-button role="button" tabindex="0" aria-label="Download statement of April 2031 (PDF)" ' +
                     'data-m="April" data-y="2031"><svg width="16" height="16"></svg></ui-button>';
      ul.insertBefore(li, ul.firstChild);
    }""")
    assert el.get_attribute("aria-label") == "Download statement of February 2031 (PDF)"


def test_a_file_apple_named_for_another_document_is_not_saved(browser, tmp_path):
    """Apple names each file for its document. A tax form whose file names
    another year than its button is not the form the app asked for, or
    the year its button names is not its tax year. Either way it is not
    saved under that year, and the trace says which part disagreed, in
    fixed words that name neither the month nor the year."""
    page, served = _open(browser, mode="misname")
    page.goto("https://card.apple.com/")
    out = tmp_path / "tax.pdf"
    trace = []
    assert not site.download_bill(page, None, "2030-12-31", out, title="Tax Document - 2030", trace=trace)
    assert not out.exists()
    said = [t for t in trace if t.get("note") == "apple named the file for another document"]
    assert said == [{"note": "apple named the file for another document", "kind": "tax",
                     "named_kind": "tax", "same_kind": True, "same_period": False}], trace
    clicked = [t for t in trace if t.get("note") == "clicked"]
    assert clicked == [{"note": "clicked", "control": "a document button"}]
    written = json.dumps(site.attempt_record(trace))
    assert "January" not in written and "2030" not in written and "2029" not in written
    # a statement, named as it should be, is still saved
    card = tmp_path / "card.pdf"
    assert site.download_bill(page, None, "2031-01-31", card, title="Apple Card Statement - January 2031")
    assert b"card January 2031" in card.read_bytes()


def test_the_name_a_browser_saved_the_file_under_is_checked_too(browser, tmp_path):
    """A real Edge or Chrome saves the file itself, into the folder the app
    watches, under Apple's name, and no download event is seen. That name
    is checked the same way before the file is taken."""
    page, served = _open(browser, mode="misname", folder=True)
    dl = tmp_path / "downloads"
    dl.mkdir()
    page.expose_function("landInFolder", lambda name, body: (dl / name).write_bytes(body.encode("latin-1")))
    page.goto("https://card.apple.com/")

    good = tmp_path / "savings.pdf"
    assert site.download_bill(page, dl, "2031-02-28", good, title="Savings Statement - February 2031")
    assert b"savings February 2031" in good.read_bytes()

    bad = tmp_path / "tax.pdf"
    trace = []
    assert not site.download_bill(page, dl, "2030-12-31", bad, title="Tax Document - 2030", trace=trace)
    assert not bad.exists()
    assert [p.name for p in dl.iterdir()] == ["1099-INT 2029 - Tax Form.pdf"]
    assert any(t.get("note") == "apple named the file for another document" for t in trace), trace


def test_a_first_press_that_does_nothing_is_made_once_more(browser, tmp_path):
    """RECORDED in the first Pilot (#52, 0.37.1). The first press on a list
    the app had just opened produced nothing at all, on the card's
    statements and on the Savings statements, and every later press on the
    same list downloaded at once. That press is made once more. The next
    document on the same list needs only its own press, and no document
    is downloaded twice."""
    page, served = _open(browser, deaf=True)
    page.goto("https://card.apple.com/")
    traces = []
    for n, (title, iso, want) in enumerate([
            ("Apple Card Statement - March 2031", "2031-03-31", b"card March 2031"),
            ("Apple Card Statement - February 2031", "2031-02-28", b"card February 2031"),
            ("Savings Statement - March 2031", "2031-03-31", b"savings March 2031"),
            ("Savings Statement - February 2031", "2031-02-28", b"savings February 2031")]):
        out = tmp_path / ("%d.pdf" % n)
        trace = []
        assert site.download_bill(page, None, iso, out, title=title, trace=trace), (title, trace)
        assert want in out.read_bytes(), title
        traces.append(trace)
    assert [sum(t.get("note") == "pressed again" for t in tr) for tr in traces] == [1, 0, 1, 0], traces
    lists = [[t["note"] for t in tr if t.get("note", "").startswith("the list was")] for tr in traces]
    assert lists == [["the list was opened for this document"], ["the list was already open"],
                     ["the list was opened for this document"], ["the list was already open"]]
    assert page.evaluate("window.presses") == 6
    assert page.evaluate("window.downloads") == 4


def test_a_press_that_works_is_never_made_again(browser, tmp_path):
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    trace = []
    assert site.download_bill(page, None, "2031-02-28", tmp_path / "card.pdf",
                              title="Apple Card Statement - February 2031", trace=trace)
    assert not any(t.get("note") == "pressed again" for t in trace), trace
    assert page.evaluate("window.presses") == 1
    assert page.evaluate("window.downloads") == 1


def test_a_button_that_never_answers_is_pressed_twice_and_no_more(browser, tmp_path):
    """Nothing is saved, the button is pressed twice in all, and what the
    trace says leaves as fixed words with no month and no year."""
    page, served = _open(browser, dead=True)
    page.goto("https://card.apple.com/")
    out = tmp_path / "card.pdf"
    trace = []
    assert not site.download_bill(page, None, "2031-02-28", out,
                                  title="Apple Card Statement - February 2031", trace=trace)
    assert not out.exists()
    assert page.evaluate("window.presses") == 2
    notes = [t.get("note") for t in trace]
    assert notes.count("clicked") == 1 and notes.count("pressed again") == 1, notes
    record = site.attempt_record(trace)
    assert {"note": "pressed again", "control": "a document button"} in record
    written = json.dumps(record)
    assert "February" not in written and "2031" not in written


def test_a_press_the_page_answered_is_not_made_again(browser, tmp_path):
    """A press that put anything new on the page was not ignored, and
    pressing again could undo what it opened. Only a press that produced
    nothing at all is made twice."""
    page, served = _open(browser, reacts=True)
    page.goto("https://card.apple.com/")
    trace = []
    assert not site.download_bill(page, None, "2031-02-28", tmp_path / "card.pdf",
                                  title="Apple Card Statement - February 2031", trace=trace)
    assert page.evaluate("window.presses") == 1
    assert not any(t.get("note") == "pressed again" for t in trace), trace


def test_the_second_press_is_caught_in_the_folder_too(browser, tmp_path):
    """A real Edge or Chrome saves the file itself into the folder the app
    watches. The file the second press sent is taken from there and the
    folder is left empty."""
    page, served = _open(browser, deaf=True, folder=True)
    dl = tmp_path / "downloads"
    dl.mkdir()
    page.expose_function("landInFolder", lambda name, body: (dl / name).write_bytes(body.encode("latin-1")))
    page.goto("https://card.apple.com/")
    out = tmp_path / "savings.pdf"
    assert site.download_bill(page, dl, "2031-02-28", out, title="Savings Statement - February 2031")
    assert b"savings February 2031" in out.read_bytes()
    assert list(dl.iterdir()) == []
    assert page.evaluate("window.presses") == 2


def test_only_a_button_whose_whole_name_dismisses_is_pressed_to_clear_an_overlay(browser):
    """An icon button named "Close Apple Card Account" starts with close,
    and its text, all the guard used to see, is empty. It is never
    pressed. A button named Close is."""
    page, served = _open(browser, overlay=True)
    page.goto("https://card.apple.com/")
    page.wait_for_selector(".promo button")
    site.dismiss_overlay(page)
    assert page.evaluate("window.pressed") == ["Close"]


def test_a_count_that_cannot_be_read_passes_no_check(monkeypatch):
    """Buttons that cannot be counted are not fewer than the link's count.
    The list is not read."""
    class Unreadable:
        def count(self):
            raise RuntimeError("the page went away")

        def element_handles(self):
            raise RuntimeError("the page went away")

    monkeypatch.setattr(site, "_controls_named", lambda *a, **k: Unreadable())
    monkeypatch.setattr(site, "_savingsy", lambda page: True)
    checks = site._list_checks(object(), site.TAX, [], 2)
    assert checks["within_its_count"] is False
    assert checks["documents_drawn"] is False


def test_download_attempt_carries_fixed_words_and_no_page_text(tmp_path, monkeypatch, capsys):
    """download-attempt.json is a file a tester is asked to attach. It was
    the trace as it stood, the clicked button's month, the words of any
    control the click revealed, and every address with digit runs masked.
    The core's own entry in the same trace is put through the same list."""
    import applecard_docs
    from paperpull_core import doc_types

    def failing(page, dl_dir, iso, out_path, title="", trace=None):
        trace.extend([
            {"note": "clicked", "control": "Download statement of March 2031 (PDF)"},
            {"note": "the tab moved", "url": "https://card.apple.com/statement/Dana-Quill/123456789",
             "content_type": "text/html; name=Dana Quill"},
            {"note": "after the click", "url": "https://card.apple.com/?who=dana.quill",
             "appeared": ["Send to Dana Quill", "a document button"], "new_tabs": 0},
            {"note": "Dana Quill wrote this", "status": 200, "type": "application/pdf",
             "url": "https://pay.example.com/Dana"},
        ])
        return False

    monkeypatch.setattr(site, "download_bill", failing)
    app = _app(SimpleNamespace(url="https://card.apple.com/savings/Dana?account=123456789"), tmp_path)
    app._dl_dir = tmp_path / "dl"
    app.paths = SimpleNamespace(diagnostics=tmp_path, folder_for=lambda category: tmp_path)
    app.progress = app.discovery = SimpleNamespace(update=lambda *a, **k: None)
    app.index_csv = SimpleNamespace(append_rows=lambda rows: None)
    monkeypatch.setattr(app, "check_session", lambda page: None)
    monkeypatch.setattr(app, "write_failure", lambda *a, **k: None)
    cat, summary, _ = doc_types.classify_document("Apple Card Statement - March 2031", app.rules)
    doc = applecard_docs.Document(title="Apple Card Statement - March 2031", category=cat,
                                  summary=summary, date="2031-03-31")
    app.download_one(app._work_page, doc, "2031-03-31 Apple Card Statement.pdf")

    text = (tmp_path / "download-attempt.json").read_text(encoding="utf-8")
    for leaked in ("Dana", "Quill", "dana", "123456789", "March", "pay.example"):
        assert leaked not in text, leaked
    record = json.loads(text)
    assert record["landed_on"] == "card:/savings/#?account"
    assert record["kind"] == "card"
    assert record["responses"][0] == {"note": "clicked", "control": None}
    assert record["responses"][1]["url"] == "card:/statement/#/#"
    assert record["responses"][1]["content_type"] == "html"
    assert record["responses"][2]["appeared"] == [None, "a document button"]
    assert record["responses"][3] == {"note": None, "status": 200, "type": "pdf", "url": "elsewhere"}
    assert "no text from your account" in capsys.readouterr().out


def test_every_word_a_trace_here_writes_is_one_the_attempt_file_keeps():
    """A note written into a trace but missing from the list of words that
    may leave would reach download-attempt.json as null. That is the safe
    way to be wrong, and this keeps it from happening quietly."""
    def written(value):
        """The words a dictionary value writes as it stands."""
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return [value.value]
        if isinstance(value, ast.IfExp):
            return written(value.body) + written(value.orelse)
        return []

    tree = ast.parse(Path(site.__file__).read_text(encoding="utf-8"))
    missing, seen = [], 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and "trace" in ast.unparse(node.func.value)):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                for value in arg.values:
                    words = written(value)
                    seen += len(words)
                    missing += [w for w in words if w not in site._TRACE_WORDS]
    assert seen > 15, seen
    assert not missing, missing
    for label in ("", "Download statement of March 2031 (PDF)", "Download PDF", "Send to Dana Quill"):
        assert site._label_mask(label) in site._TRACE_WORDS, label
    for message in ("Timeout 8000ms exceeded", "strict mode violation", "element is not visible",
                    "<div> intercepts pointer events", "Element is not attached to the DOM", "boom"):
        assert site._click_failure(RuntimeError(message)) in site._TRACE_WORDS, message


# -- the file the page made, when the browser's own download never arrives ------
#
# RECORDED (#52, 0.38.0). The tester's Chrome downloaded both August
# statements twice, with its own download menu open in the address bar, and
# nothing reached the folder the app watches or its download event. Here the
# browser's download is made to fail the same way, so the only way left to
# save the file is where the page built it.

def _downloads_never_arrive(monkeypatch):
    """Neither the download event nor the folder gives the file up. The
    event is taken through capture.take_download, which reads both, so that
    is where the loss is made."""

    def lost(download, dl_dir, before, out_path, **how):
        return ""

    monkeypatch.setattr(site, "_take_download", lost)


def test_the_file_the_page_made_is_taken_when_the_download_never_arrives(browser, tmp_path, monkeypatch):
    _downloads_never_arrive(monkeypatch)
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    out = tmp_path / "card.pdf"
    trace = []
    assert site.download_bill(page, None, "2031-02-28", out,
                              title="Apple Card Statement - February 2031", trace=trace), trace
    assert b"card February 2031" in out.read_bytes()
    made = [t for t in trace if t.get("note") == "the page made the document itself"]
    assert made == [{"note": "the page made the document itself", "named": True}], trace
    assert page.evaluate("window.presses") == 1


def test_a_file_made_for_the_document_before_is_never_taken_for_the_next(browser, tmp_path, monkeypatch):
    """Arming the watch again for each document forgets what it kept, so
    the second document can only be taken from its own press."""
    _downloads_never_arrive(monkeypatch)
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    for n, (title, iso, want) in enumerate([
            ("Apple Card Statement - February 2031", "2031-02-28", b"card February 2031"),
            ("Apple Card Statement - January 2031", "2031-01-31", b"card January 2031")]):
        out = tmp_path / ("%d.pdf" % n)
        assert site.download_bill(page, None, iso, out, title=title), title
        assert want in out.read_bytes(), title


def test_a_made_file_apple_named_for_another_document_is_refused(browser, tmp_path, monkeypatch):
    _downloads_never_arrive(monkeypatch)
    page, served = _open(browser, mode="misname")
    page.goto("https://card.apple.com/")
    out = tmp_path / "tax.pdf"
    trace = []
    assert not site.download_bill(page, None, "2030-12-31", out, title="Tax Document - 2030", trace=trace)
    assert not out.exists()
    assert any(t.get("note") == "apple named the file for another document" for t in trace), trace
    assert not any(t.get("note") == "the page made the document itself" for t in trace), trace


def test_only_apples_own_hosts_may_hand_over_a_pdf_in_passing():
    assert site._is_apple_file_host("https://card.apple.com/x.pdf")
    assert site._is_apple_file_host("https://statements.apple.com/doc?id=1")
    assert site._is_apple_file_host("https://apple.com/a.pdf")
    for url in ("http://statements.apple.com/a.pdf", "https://apple.com.example.net/a.pdf",
                "https://evilapple.com/a.pdf", "https://user@statements.apple.com/a.pdf",
                "https://statements.apple.com:8443/a.pdf", "not a url", ""):
        assert not site._is_apple_file_host(url), url


# -- signed out partway through discovery ---------------------------------------
#
# Discovery opens the three lists in turn, and Apple can sign the person out
# between one and the next. The front page is then Apple's sign-in. A run
# started from a terminal asks the person to sign in again and opens the
# card's statements, and the list that would not open was left out of the
# run. When that was the last one, the tax forms, nothing said so, because
# the card's list had been found, and the run read as clean.

SIGN_IN = """<!doctype html><html><head><title>Apple Card</title></head><body>
<main><h1>Sign in to Apple Card</h1><form>
<label>Apple Account <input type="email"></label>
<label>Password <input type="password"></label>
<button type="button">Continue</button></form></main></body></html>"""

EVERY_DOCUMENT = sorted(
    ["Apple Card Statement - " + m for m in ("March 2031", "February 2031", "January 2031",
                                             "December 2030")]
    + ["Savings Statement - " + m for m in ("March 2031", "February 2031", "January 2031")]
    + ["Tax Document - 2030", "Tax Document - 2029"])


def _signed_out_at(page, monkeypatch, kind):
    """The session runs out just as discovery opens `kind`'s list, after the
    lists before it were read signed in. Tied to the app opening that list,
    not to a clock. From then on the front page and /savings answer Apple's
    sign-in, until whoever answers the question has signed in again."""
    session = {"signed_in": True, "lapsed": []}

    def sign_in(route, request):
        if session["signed_in"] or urlsplit(request.url).path not in ("/", "/savings"):
            route.fallback()
        else:
            route.fulfill(status=200, content_type="text/html", body=SIGN_IN)

    # Added after the made-up site's own route, so it is asked first.
    page.context.route("https://card.apple.com/**", sign_in)
    real = site.goto_section

    def opening(pg, k, trace=None):
        if k == kind and not session["lapsed"]:
            session["lapsed"].append(k)
            session["signed_in"] = False
            # The site notices and puts its sign-in up in place of the list.
            pg.reload()
        return real(pg, k, trace)

    monkeypatch.setattr(site, "goto_section", opening)
    return session


def _answering(monkeypatch, session, signs_in_at=1, limit=5):
    """Somebody at the console, who presses Enter at every question and has
    signed in again by the `signs_in_at`th. Past `limit` questions they give
    up with Ctrl+C, so a loop that asks forever fails here rather than
    hanging the suite."""
    from paperpull_core import browser as browser_launcher
    asked = []

    def answer(prompt):
        asked.append(prompt)
        if len(asked) > limit:
            raise KeyboardInterrupt
        if len(asked) >= signs_in_at:
            session["signed_in"] = True
        return ""

    monkeypatch.setattr(browser_launcher, "ask_or_none", answer)
    return asked


def _discover(page, tmp_path):
    """Discovery on the page, and the title of every document it found."""
    from storage import JsonStore
    app = _app(page, tmp_path)
    app.progress = JsonStore(tmp_path / "progress.json")
    app.cmd_discover(quiet=True)
    return sorted(v["title"] for v in app.discovery.data.values())


@pytest.mark.parametrize("kind", [site.SAVINGS, site.TAX])
def test_a_list_the_session_ran_out_on_is_read_once_the_person_has_signed_in(
        browser, tmp_path, monkeypatch, capsys, kind):
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    session = _signed_out_at(page, monkeypatch, kind)
    asked = _answering(monkeypatch, session)

    titles = _discover(page, tmp_path)
    out = " ".join(capsys.readouterr().out.split())

    assert session["lapsed"] == [kind]
    assert len(asked) == 1 and "signed in" in asked[0], asked
    assert "appears to have signed you out" in out, out
    assert [t for t in titles if site.kind_of_title(t) == kind] == \
        [t for t in EVERY_DOCUMENT if site.kind_of_title(t) == kind], titles
    assert titles == EVERY_DOCUMENT
    assert not list(tmp_path.glob("failure-*.json"))


def test_a_person_who_answers_before_signing_in_is_asked_again(browser, tmp_path, monkeypatch):
    """Enter pressed while the sign-in is still up. The tax forms are not
    left out for that. The question is put again, and they are read once
    the person really has signed in."""
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    session = _signed_out_at(page, monkeypatch, site.TAX)
    asked = _answering(monkeypatch, session, signs_in_at=2)

    assert _discover(page, tmp_path) == EVERY_DOCUMENT
    assert len(asked) == 2, asked


def test_under_the_panel_discovery_still_stops_where_the_session_ran_out(
        browser, tmp_path, monkeypatch, capsys):
    """Nobody to ask. The run stops as it did before and says to press
    Resume, rather than going on without the list."""
    from paperpull_core import browser as browser_launcher
    page, served = _open(browser)
    page.goto("https://card.apple.com/")
    _signed_out_at(page, monkeypatch, site.TAX)
    monkeypatch.setattr(browser_launcher, "ask_or_none", lambda prompt: None)

    with pytest.raises(SystemExit) as stopped:
        _discover(page, tmp_path)
    out = " ".join(capsys.readouterr().out.split())

    assert stopped.value.code == 0, out
    assert "press Resume" in out, out
