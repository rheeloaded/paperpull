"""Each card's statements are saved as that card's, read from the PDFs
themselves, in a real browser attached the way it is at home.

American Express writes the card on show in its switcher and draws the list
of that card a moment later, in place, with the address never changing. So a
run that reads the list as soon as the switcher moves reads the old card's
list as the new card's. A monthly statement of the wrong card is then only
not found, but a year-end summary carries nothing but its year, the same on
every card, so the two cards' summaries come out swapped, with both marked
Completed.

Every Download is on the page twice, a copy for a wide window and a hidden
copy for a narrow one, and either copy can come first in the page, so these
runs are made at both widths with both orders.

The browser is started as a program of its own with a debugging port and the
app attaches over CDP and runs its own Run All. American Express is a made-up
host name the browser is told to find on this machine, and every other name
fails to resolve. Its page replaces eval as American Express does, so
page.evaluate fails on it as it fails there. Each PDF the made-up site hands
over says the card of the list on show when its Download was pressed, so a
run is judged by the bytes it kept and not by the names it gave them. Every
name, number and date is invented.
"""
import csv
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import amex_docs as app_mod
import amex_site as site
from paperpull_core import browser as browser_launcher
from paperpull_core import pressing, run_reporting, testkit
from paperpull_core.models import State
from paperpull_core.receipt_pdf import pdf_text

AMEX_HOST = "global.americanexpress.test"
HOSTS = ("--host-resolver-rules=MAP %s 127.0.0.1, MAP * ~NOTFOUND , EXCLUDE 127.0.0.1"
         % AMEX_HOST)
TITLE = "Statements and Year End Summaries"
WIDE, NARROW = 1200, 620

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>%(title)s</title>
<script>
window.eval = function () { throw new Error('eval is disabled'); };
window.CFG = %(cfg)s;
function said(what) { navigator.sendBeacon('/pressed/' + what); }
</script>
<style>
[hidden] { display: none !important; }
html, body { margin: 0; font: 16px sans-serif; }
.row { height: 56px; border-top: 1px solid #ccc; line-height: 56px; padding-left: 16px; }
.row button { margin-left: 16px; width: 110px; height: 34px; }
.row button.mobile, .swc.mobile { display: none; }
.swc.gone { display: none !important; }
@media (max-width: 700px) {
  .row button.desk, .swc.desk { display: none; }
  .row button.mobile { display: inline-block; }
  .swc.mobile { display: block; }
}
#lb { border: 1px solid #333; width: 300px; }
#lb [role=option] { display: block; height: 40px; width: 300px; }
.dialog { position: fixed; left: 40px; top: 60px; width: 380px; background: #fff; z-index: 5;
          padding: 16px; border: 1px solid #333; }
.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.3); z-index: 4; }
</style></head><body>
<main>
<h1>%(title)s</h1>
<div id="sw"></div>
<section id="table-area"></section>
</main>
<div class="backdrop" id="backdrop" hidden></div>
<div class="dialog" id="filetype" role="dialog" aria-modal="true" aria-label="Select File Type" hidden>
  <h3>Select File Type</h3>
  <div><input type="radio" id="ft-pdf" name="ft" value="statement_pdf">
    <label for="ft-pdf">Billing Statement (PDF)</label></div>
  <div><input type="radio" id="ft-csv" name="ft" value="csv">
    <label for="ft-csv">Spreadsheet (CSV)</label></div>
  <div><button type="button" id="ft-cancel">Cancel</button>
  <a href="#" role="button" id="myca-activity-download-footer-download-confirm-anchor"
     data-test-id="myca-activity-download-footer-download-confirm-anchor">&#x2913;</a></div>
</div>
<script>
const C = CFG.cards;
let shownCard = CFG.start;   // what the switcher says
let listCard = CFG.start;    // whose list the rows are
let current = null;
let switches = 0;
const P = 'myca-activity-statements/common/Table/';
function button(kind, testid) {
  return '<button class="dl ' + kind + '" data-testid="' + testid + '">Download</button>';
}
function row(kind, when) {
  const t = P + (kind === 'ye' ? 'year-end-summary/' : 'recent-statements/') + when +
            '/download-button';
  const copies = [button('desk', t), button('mobile', t)];
  if (CFG.narrow_copy_first) copies.reverse();
  return '<div class="row">' + (kind === 'ye' ? 'Year End Summary ' : 'Statement closing ') + when +
    copies.join('') + '</div>';
}
function listHtml(c) {
  if (!c.dates.length && !c.years.length) return '<p class="msg">No statements available</p>';
  return c.dates.map(d => row('st', d)).join('') + c.years.map(y => row('ye', y)).join('');
}
const area = document.getElementById('table-area');
function drawList(i) {
  listCard = i;
  area.innerHTML = listHtml(C[i]);
}
function card(i) {
  return '<span data-testid="simple_switcher_display_name">' + C[i].name + '</span>' +
         '<span data-testid="simple_switcher_display_number">••••' + C[i].digits + '</span>';
}
function firstCopyShows() {
  const b = document.querySelector('[data-testid$="/download-button"]');
  return b ? getComputedStyle(b).display !== 'none' : null;
}
function drawSwitcher() {
  const sw = document.getElementById('sw');
  if (CFG.switcher === 'none') return;
  if (CFG.switcher === 'off') {
    sw.innerHTML = '<button disabled role="combobox" aria-expanded="false" ' +
      'data-testid="simple_switcher_combobox"><div data-testid="simple_switcher_selected_option_display">' +
      card(shownCard) + '</div></button>';
    return;
  }
  const copy = (kind) => '<div class="swc ' + kind + (CFG.switcher_gone ? ' gone' : '') + '">' +
    '<div role="combobox" tabindex="0" aria-expanded="false" style="cursor:pointer; width:300px" ' +
    'data-testid="simple_switcher_combobox"><div data-testid="simple_switcher_selected_option_display">' +
    card(shownCard) + '</div></div></div>';
  const copies = CFG.switcher_copies ? ['desk', 'mobile'] : ['only'];
  if (CFG.narrow_copy_first) copies.reverse();
  sw.innerHTML = copies.map(copy).join('') + '<div role="listbox" id="lb" hidden></div>';
  const lb = document.getElementById('lb');
  if (CFG.switcher !== 'no_options') {
    lb.innerHTML = C.map((c, i) => (c.off
      ? '<button disabled role="option" data-testid="simple_switcher_product_option_' + i + '">'
      : '<div role="option" data-testid="simple_switcher_product_option_' + i + '">') + card(i) +
      (c.off ? '</button>' : '</div>')).join('');
  }
  const copyOf = document.querySelectorAll('[data-testid="simple_switcher_combobox"]');
  for (const cb of copyOf) cb.addEventListener('click', () => {
    said('switcher/first-copy-shows/' + (getComputedStyle(copyOf[0].parentNode).display !== 'none'));
    if (CFG.switcher === 'no_options') return;
    const open = cb.getAttribute('aria-expanded') === 'true';
    cb.setAttribute('aria-expanded', open ? 'false' : 'true');
    lb.hidden = open;
  });
  lb.addEventListener('click', (e) => {
    const o = e.target.closest('[role=option]');
    if (!o || o.disabled) return;
    const i = Number(o.dataset.testid.split('_').pop());
    said('option/' + i + '/first-copy-shows/' + firstCopyShows());
    for (const cb of copyOf) cb.setAttribute('aria-expanded', 'false');
    lb.hidden = true;
    if (CFG.address_moves_first) history.pushState({}, '', '/activity/statements?account_key=KEY' + i);
    setTimeout(() => {
      shownCard = i;
      for (const d of document.querySelectorAll('[data-testid="simple_switcher_selected_option_display"]'))
        d.innerHTML = card(i);
    }, CFG.switch_ms);
    const late = CFG.list_ms_of[++switches] ?? CFG.list_ms;
    if (late >= 0) setTimeout(() => drawList(i), late);
  });
}
drawSwitcher();
if (CFG.option_copies) {
  const copies = document.getElementById('lb').cloneNode(true);
  copies.removeAttribute('id');
  copies.hidden = false;
  const hidden = document.createElement('div');
  hidden.style.display = 'none';
  hidden.appendChild(copies);
  document.getElementById('sw')[CFG.option_copies](hidden);
}
if (CFG.hidden_options.length) {
  const group = document.createElement('div');
  group.style.display = 'none';
  group.innerHTML = CFG.hidden_options.map((c, i) => '<div role="option" ' +
    'data-testid="simple_switcher_product_option_hidden' + i + '">' +
    '<span data-testid="simple_switcher_display_name">' + c.name + '</span>' +
    '<span data-testid="simple_switcher_display_number">••••' + c.digits + '</span></div>').join('');
  document.getElementById('lb').appendChild(group);
}
if (CFG.tip_over_switcher) {
  const box = document.getElementById('sw');
  box.style.position = 'relative';
  box.insertAdjacentHTML('beforeend', '<div style="position:absolute;left:0;top:0;width:100%%;' +
    'height:100%%;background:#ffc;z-index:3">Tip</div>');
}
if (!CFG.list_never) drawList(CFG.start);
const dialog = document.getElementById('filetype');
const backdrop = document.getElementById('backdrop');
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-testid$="/download-button"]');
  if (!b) return;
  const parts = b.dataset.testid.split('/');
  current = (parts.includes('year-end-summary') ? 'ye-' : 'st-') + parts[parts.length - 2];
  for (const r of document.querySelectorAll('input[name=ft]')) r.checked = false;
  backdrop.hidden = false; dialog.hidden = false;
});
document.getElementById('ft-cancel').addEventListener('click', () => {
  dialog.hidden = true; backdrop.hidden = true;
});
document.querySelector('[data-test-id$="download-footer-download-confirm-anchor"]')
  .addEventListener('click', (e) => {
    e.preventDefault();
    const kind = document.getElementById('ft-pdf').checked ? 'pdf' : 'csv';
    location.href = '/download/' + C[listCard].digits + '/' + current + '.' + kind;
  });
if (CFG.dialog_left_open) { backdrop.hidden = false; dialog.hidden = false; }
</script>
</body></html>"""

A = dict(name="Alpha Card", digits="11111", dates=["2030-11-11"], years=["2030"])
B = dict(name="Bravo Card", digits="22222", dates=["2030-11-22"], years=["2030"])
EMPTY_ONE = dict(name="Empty One", digits="33333", dates=[], years=[])
EMPTY_TWO = dict(name="Empty Two", digits="44444", dates=[], years=[])
SOLO = dict(name="Solo Card", digits="77777", dates=["2030-11-07"], years=["2030"])
CANCELED = dict(name="Canceled Card", digits="55555", dates=["2029-05-05"], years=["2029"], off=True)


class FakeAmex:
    """One made-up American Express, of a test's own. The switcher moves
    `switch_ms` after a card is pressed and the card's list comes `list_ms`
    after, the old list showing until then. `list_ms_of` gives the nth switch
    a time of its own, and a time below nought means its list never comes."""

    def __init__(self, **cfg):
        self.cfg = dict(cards=[A, B], start=0, switch_ms=100, list_ms=1500, switcher="normal",
                        narrow_copy_first=False, address_moves_first=False,
                        switcher_copies=False, switcher_gone=False, list_ms_of={},
                        tip_over_switcher=False, dialog_left_open=False, option_copies="",
                        hidden_options=[])
        self.cfg.update(cfg)
        self.pressed = []
        self.downloads = []

    def page(self):
        return PAGE % {"title": TITLE, "cfg": json.dumps(self.cfg)}


def _handler(fake):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, data, kind, extra=()):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            path = urlsplit(self.path).path
            if host != AMEX_HOST:
                self.send_error(404)
            elif path == "/activity/statements":
                self._send(fake.page().encode("utf-8"), "text/html; charset=utf-8")
            elif path.startswith("/download/"):
                _, _, digits, name = path.split("/")
                fake.downloads.append(digits + "/" + name)
                body = testkit.text_pdf(["American Express", "LIST OF CARD %s" % digits,
                                         name.rsplit(".", 1)[0]])
                self._send(body, "application/pdf",
                           [("Content-Disposition", 'attachment; filename="statement-%s"' % name)])
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            if path.startswith("/pressed/"):
                fake.pressed.append(path[len("/pressed/"):])
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture()
def serve():
    """Start a made-up American Express for a test, on a port of its own."""
    servers = []

    def start(**cfg):
        fake = FakeAmex(**cfg)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
        httpd.block_on_close = False
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        fake.port = httpd.server_address[1]
        servers.append(httpd)
        return fake

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(scope="module")
def browser_exe():
    pytest.importorskip("playwright.sync_api")
    found = browser_launcher.browser_candidates(mode=browser_launcher.BUNDLED)
    if not found:
        pytest.skip("no browser to drive")
    return found[0][1]


@pytest.fixture(scope="module")
def attached(browser_exe, tmp_path_factory):
    try:
        with testkit.drawn_browser(browser_exe, lambda: tmp_path_factory.mktemp("attached-profile"),
                                   args=(HOSTS,)) as url:
            yield url
    except testkit.NoDebugPort:
        pytest.skip("the browser opened no debugging port")


@pytest.fixture(autouse=True)
def on_the_made_up_site(monkeypatch):
    """American Express is the made-up site. Opening the statements page
    waits for the first copy of a Download to show, which in a window where
    that copy is hidden is the whole of this wait for every document, so it
    is cut to fit a test."""
    monkeypatch.setattr(site, "is_safe_url",
                        lambda url: urlsplit(url or "").hostname == AMEX_HOST)
    monkeypatch.setattr(site, "LIST_WAIT_MS", 2000)


def their_tab(attached, amex, width=WIDE):
    """The person's American Express tab, open on the statements page, the
    only tab in the browser, in a window `width` pixels wide."""
    from playwright.sync_api import sync_playwright
    at = "http://%s:%d/activity/statements" % (AMEX_HOST, amex.port)
    tab = testkit.open_tab(attached, at, TITLE)
    testkit.keep_only(attached, {tab})
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(attached)
        page = [t for t in browser.contexts[0].pages if AMEX_HOST in (t.url or "")][0]
        cdp = page.context.new_cdp_session(page)
        window = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds",
                 {"windowId": window, "bounds": {"width": width, "height": 900}})
        cdp.detach()
        browser.close()


def config(tmp_path, cdp_url):
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out),
        "profile_dir": str(tmp_path / "launched-profile"), "cdp_url": cdp_url,
        "document_types": ["Statement", "Year-End Summary"], "default_start_date": "",
        "delay_min_seconds": 0, "delay_max_seconds": 0}), encoding="utf-8")
    return cfg


def run_all(cfg, capsys, *flags):
    """A run as the panel starts it, Run All unless told, and what it said
    and how it ended."""
    code = "finished"
    try:
        code = app_mod.main(list(flags or ("--all", "--yes")) + ["--config", str(cfg)])
    except SystemExit as stopped:
        code = stopped.code
    return code, capsys.readouterr().out


def folded(out):
    return " ".join(out.split())


def panel_reads(out):
    for line in out.splitlines():
        if line.startswith(run_reporting.PREFIX):
            return json.loads(line[len(run_reporting.PREFIX):])
    raise AssertionError("no result line for the panel in\n" + out)


def records(tmp_path, name):
    path = tmp_path / "out" / name
    got = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: v for k, v in got.items() if isinstance(v, dict) and "category" in v}


def noted_whole(tmp_path):
    return json.loads((tmp_path / "out" / "last-listing.json").read_text(encoding="utf-8"))["complete"]


def saved(tmp_path):
    """Each record the run finished, with the card its PDF's own bytes say
    it came from, by the record's key."""
    out = {}
    for key, rec in records(tmp_path, "progress.json").items():
        path = Path(rec.get("pdf_path") or "")
        words = pdf_text(path).split() if path.is_file() else []
        out[key] = {"state": rec.get("state"), "account": rec.get("account"), "name": path.name,
                    "date": rec.get("date"), "category": rec.get("category"),
                    "card": words[words.index("CARD") + 1] if "CARD" in words else ""}
    return out


def digits_of(account):
    return account.rsplit("(", 1)[1].rstrip(")")


def test_the_made_up_page_refuses_evaluate_as_american_express_does(attached, serve):
    """Not vacuous. On this page page.evaluate and locator.evaluate fail as
    they fail on American Express, and a locator still reads it, so what the
    app does here is what it can do there."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    their_tab(attached, serve())
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(attached)
        page = [t for t in browser.contexts[0].pages if AMEX_HOST in (t.url or "")][0]
        with pytest.raises(PlaywrightError, match="eval is disabled"):
            page.evaluate("1 + 1")
        with pytest.raises(PlaywrightError, match="eval is disabled"):
            page.locator("h1").evaluate("e => e.tagName")
        assert page.locator("[data-testid$='/download-button']").count() == 4
        browser.close()


@pytest.mark.parametrize("width,narrow_copy_first,first_copy_shows", [
    (WIDE, False, True), (NARROW, False, False), (WIDE, True, False), (NARROW, True, True)],
    ids=["wide", "narrow", "wide-narrow-copy-first", "narrow-narrow-copy-first"])
def test_each_cards_statements_and_summary_are_its_own(attached, serve, tmp_path, capsys, width,
                                                       narrow_copy_first, first_copy_shows):
    """The switcher moves at once and the list a second and a half later.
    Every record of a card holds that card's own dates, and every PDF, the
    two year-end summaries with the one date above all, came from that
    card's own list."""
    amex = serve(narrow_copy_first=narrow_copy_first)
    their_tab(attached, amex, width)
    code, out = run_all(config(tmp_path, attached), capsys)

    # Not vacuous. The window is the one the test says, so in two of these
    # the first copy of a Download is the hidden one.
    pressed = [p for p in amex.pressed if p.startswith("option/1/")]
    assert pressed and pressed[0].endswith("first-copy-shows/%s" % str(first_copy_shows).lower()), \
        amex.pressed
    holds_each_cards_own(tmp_path, out)


@pytest.mark.parametrize("width,narrow_copy_first", [(WIDE, True), (NARROW, False)],
                         ids=["wide", "narrow"])
def test_a_hidden_first_copy_of_the_switcher_costs_no_card(attached, serve, tmp_path, capsys, width,
                                                           narrow_copy_first):
    """The switcher is on the page twice like every other control, and the
    first copy is the hidden one at this width. Both cards are read and each
    keeps its own. Going by the first copy read as no switcher at all, so two
    cards went as one with the list noted whole and nothing said."""
    amex = serve(switcher_copies=True, narrow_copy_first=narrow_copy_first)
    their_tab(attached, amex, width)
    code, out = run_all(config(tmp_path, attached), capsys)

    assert "switcher/first-copy-shows/false" in amex.pressed, amex.pressed
    holds_each_cards_own(tmp_path, out)


def holds_each_cards_own(tmp_path, out):
    """Each card's records hold its own dates, and each PDF came from its own
    card's list, read from the PDF. The list is noted whole."""
    said = folded(out)
    listed = records(tmp_path, "discovery.json")
    for rec in listed.values():
        card = A if digits_of(rec["account"]) == A["digits"] else B
        assert rec["date"] in card["dates"] + ["%s-12-31" % y for y in card["years"]], \
            "%s was listed under %s\n%s" % (rec["date"], rec["account"], said)
    assert len(listed) == 4, sorted(listed)

    kept = saved(tmp_path)
    assert len(kept) == 4, (kept, said)
    for rec in kept.values():
        assert rec["state"] == State.COMPLETED.value, (rec, said)
        assert rec["card"] == digits_of(rec["account"]), \
            "%s saved as %s came from the list of %s" % (rec["name"], rec["account"], rec["card"])
    summaries = {r["account"]: r["card"] for r in kept.values() if r["category"] == "Year-End Summary"}
    assert summaries == {"Alpha Card (11111)": "11111", "Bravo Card (22222)": "22222"}
    assert not any(source_urls(tmp_path))
    assert noted_whole(tmp_path) is True
    assert panel_reads(out)["stopped"] == 0


def test_a_list_that_never_goes_stops_the_run_in_a_narrow_window(attached, serve, tmp_path, capsys):
    """The list comes after the wait for the old one has run out, in the
    window where the first copy is the hidden one. The run stops with the
    switch unread, and nothing is listed under the second card."""
    amex = serve(list_ms=8000)
    their_tab(attached, amex, NARROW)
    code, out = run_all(config(tmp_path, attached), capsys)

    assert panel_reads(out)["stopped"] == 1, folded(out)
    assert "the card's statements did not open" in folded(out)
    assert not [r for r in records(tmp_path, "discovery.json").values()
                if digits_of(r["account"]) == B["digits"]]
    assert saved(tmp_path) == {}
    assert noted_whole(tmp_path) is False


def test_a_turned_off_card_costs_nothing_but_itself(attached, serve, tmp_path, capsys, monkeypatch):
    """Three cards with the middle one's option turned off. Both other cards'
    PDFs are saved, each its own. The turned off card is said by name, in
    what the run says first and in what it says last, and counted, and it is
    in the failure file without its name. The list is not noted as whole, so
    the Resume after it says so and stops."""
    monkeypatch.setattr(pressing, "PRESS_MS", 1000)
    amex = serve(cards=[A, CANCELED, B], list_ms=500)
    their_tab(attached, amex)
    cfg = config(tmp_path, attached)
    code, out = run_all(cfg, capsys)
    said = folded(out)

    kept = saved(tmp_path)
    assert sorted(r["card"] for r in kept.values()) == ["11111", "11111", "22222", "22222"], (kept, said)
    for rec in kept.values():
        assert rec["state"] == State.COMPLETED.value and rec["card"] == digits_of(rec["account"]), rec
    assert not [r for r in records(tmp_path, "discovery.json").values()
                if r["account"] == "Canceled Card (55555)"]
    assert not [p for p in amex.pressed if p.startswith("option/1")], amex.pressed

    first = "Canceled Card (55555) is turned off in the card switcher"
    assert first in said
    assert out.rstrip().splitlines()[-1].startswith(run_reporting.PREFIX)
    assert "!! Not read: Canceled Card (55555)" in out[out.rindex("[4/4]"):]
    assert "Discovery complete" not in said
    result = panel_reads(out)
    assert (result["manual_review"], result["stopped"], result["new_files"]) == (1, 0, 4), result
    assert noted_whole(tmp_path) is False

    failures = sorted((tmp_path / "out").rglob("failure-*.json"))
    assert len(failures) == 1
    written = failures[0].read_text(encoding="utf-8")
    assert "a card option is turned off" in written
    assert "Canceled" not in written and "55555" not in written

    code, out = run_all(cfg, capsys, "--resume")
    assert "stopped before it read the whole list" in folded(out)
    assert panel_reads(out)["list_not_read"] == 1


def test_a_pilot_does_not_call_a_list_with_a_card_left_out_clean(attached, serve, tmp_path, capsys,
                                                                 monkeypatch):
    monkeypatch.setattr(pressing, "PRESS_MS", 1000)
    amex = serve(cards=[A, CANCELED, B], list_ms=500)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys, "--pilot")
    report = folded(out[out.index("PILOT RESULTS"):])

    assert "No problems detected" not in report
    assert "Not read: Canceled Card (55555)" in report


def test_two_empty_cards_in_a_row_do_not_cost_the_third_card(attached, serve, tmp_path, capsys):
    """Two empty cards and then a full one, with the page's own words for the
    first two. After an empty card there are no Download buttons, so the wait
    has only the words to go by, and the wait held the region around them,
    which never goes, and stopped the run at the second card."""
    amex = serve(cards=[EMPTY_ONE, EMPTY_TWO, B], list_ms=1000)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    said = folded(out)

    kept = saved(tmp_path)
    assert sorted((r["category"], r["card"]) for r in kept.values()) == [
        ("Statement", "22222"), ("Year-End Summary", "22222")], (kept, said)
    for rec in kept.values():
        assert rec["state"] == State.COMPLETED.value and rec["account"] == "Bravo Card (22222)", rec
    assert noted_whole(tmp_path) is True
    assert panel_reads(out)["stopped"] == 0, said


@pytest.mark.parametrize("cfg,success", [
    (dict(list_never=True), False), (dict(), True), (dict(cards=[EMPTY_ONE]), True)],
    ids=["nothing-drawn", "a-list", "the-pages-own-empty-words"])
def test_login_says_success_only_on_a_list_it_saw(attached, serve, tmp_path, capsys, cfg, success):
    """A tab at the statements address with nothing drawn says no session.
    A blank page once read as signed in on another provider."""
    amex = serve(switcher="none", **cfg)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys, "--login")
    said = folded(out)

    assert ("Success: connected" in said) is success, said
    assert ("the Documents list did not load" in said) is not success, said


# What a person with one card has on main, word for word. A key of a record
# that changes downloads the whole history again under a new name.
ONE_CARD = {
    "Statement:2030-11-07:Monthly Statement - November 7, 2030:Unnamed":
        "2030-11-07 American Express Monthly Statement.pdf",
    "Year-End Summary:2030-12-31:2030 Year-End Summary:Unnamed":
        "2030-12-31 American Express Year-End Summary.pdf",
}


def source_urls(tmp_path):
    """The Source URL of each row of the index, which main leaves empty."""
    index = [p for p in (tmp_path / "out").rglob("*.csv")
             if "Source URL" in p.read_text(encoding="utf-8-sig").splitlines()[0]]
    with index[0].open(encoding="utf-8-sig", newline="") as f:
        return [row["Source URL"] for row in csv.DictReader(f)]


def holds_one_cards_archive(tmp_path):
    kept = saved(tmp_path)
    assert {k: r["name"] for k, r in kept.items()} == ONE_CARD
    assert source_urls(tmp_path) == ["", ""]
    for rec in kept.values():
        assert rec["state"] == State.COMPLETED.value and rec["account"] == "", rec
        assert rec["card"] == SOLO["digits"], rec


@pytest.mark.parametrize("switcher", ["none", "normal"])
def test_one_card_that_reads_as_one_card_keeps_its_archive_and_says_nothing(
        attached, serve, tmp_path, capsys, switcher):
    amex = serve(cards=[SOLO], switcher=switcher)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    holds_one_cards_archive(tmp_path)
    assert noted_whole(tmp_path) is True
    assert panel_reads(out)["manual_review"] == 0
    assert "could not be read" not in out and "Not read" not in out


@pytest.mark.parametrize("cfg,shown", [
    (dict(switcher="off"), "Solo Card (77777)"), (dict(switcher="no_options"), "Solo Card (77777)"),
    (dict(switcher_copies=True, switcher_gone=True), "the card on show"),
    (dict(tip_over_switcher=True), "Solo Card (77777)")],
    ids=["off", "no_options", "none_showing", "covered"])
def test_a_switcher_that_cannot_be_read_keeps_one_cards_path_and_is_not_quiet(
        attached, serve, tmp_path, capsys, monkeypatch, cfg, shown):
    """Nothing pressed the switcher before cards were told apart, so this
    person's run works today and has to go on working, with the same keys,
    names and bytes. It may be several cards behind a broken switcher, so the
    run says what it read, counts it, and does not note the list as whole."""
    monkeypatch.setattr(pressing, "PRESS_MS", 1000)
    monkeypatch.setattr(site, "LINK_WAIT_MS", 1000)
    amex = serve(cards=[SOLO], **cfg)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    said = folded(out)

    holds_one_cards_archive(tmp_path)
    assert "could not be read, so only %s was read" % shown in said
    assert "!! Not read: any card but %s" % shown in out[out.rindex("[2/2]"):]
    assert "Discovery complete" not in said
    result = panel_reads(out)
    assert (result["manual_review"], result["stopped"], result["new_files"]) == (1, 0, 2), result
    assert noted_whole(tmp_path) is False
    failures = sorted((tmp_path / "out").rglob("failure-*.json"))
    assert len(failures) == 1
    written = failures[0].read_text(encoding="utf-8")
    assert "the card options did not show" in written
    assert "Solo" not in written and "77777" not in written


@pytest.mark.parametrize("cfg,shown", [
    (dict(switcher="no_options"), "Alpha Card (11111)"),
    (dict(switcher_copies=True, switcher_gone=True), "the card on show")],
    ids=["no_options", "none_showing"])
def test_several_cards_behind_a_switcher_that_cannot_be_read_are_not_called_whole(
        attached, serve, tmp_path, capsys, monkeypatch, cfg, shown):
    """Two cards behind a broken switcher on a first run. What can be read is
    read, the second card is said not to be, and Resume does not call it done."""
    monkeypatch.setattr(site, "LINK_WAIT_MS", 1000)
    amex = serve(**cfg)
    their_tab(attached, amex)
    conf = config(tmp_path, attached)
    code, out = run_all(conf, capsys)

    kept = saved(tmp_path)
    assert sorted(r["card"] for r in kept.values()) == ["11111", "11111"], kept
    assert "only %s was read" % shown in folded(out)
    assert noted_whole(tmp_path) is False

    code, out = run_all(conf, capsys, "--resume")
    assert "everything in scope is complete" not in folded(out)
    assert panel_reads(out)["list_not_read"] == 1


@pytest.mark.parametrize("switcher", ["no_options", "none"])
def test_a_switcher_that_cannot_be_read_stops_an_archive_filed_by_card(attached, serve, tmp_path,
                                                                       capsys, monkeypatch, switcher):
    """An archive filed by card is not one card, and carrying on would save
    its statements again under no card's name, with every other card unread.
    A page with no switcher at all is no different for such an archive."""
    cfg = config(tmp_path, attached)
    their_tab(attached, serve())
    code, out = run_all(cfg, capsys)
    assert len(saved(tmp_path)) == 4

    monkeypatch.setattr(site, "LINK_WAIT_MS", 1000)
    their_tab(attached, serve(switcher=switcher))
    code, out = run_all(cfg, capsys)

    assert panel_reads(out)["stopped"] == 1, folded(out)
    assert "holds statements filed by card" in folded(out)
    assert all(r["account"] for r in records(tmp_path, "discovery.json").values())
    assert len(saved(tmp_path)) == 4
    assert noted_whole(tmp_path) is False


def test_an_address_that_moves_first_is_not_the_old_list_going(attached, serve, tmp_path, capsys):
    """The address moves as the card is pressed and the old list stays past
    the wait for it. The address never moves on the real page, so all it can
    do here is say the old list went while it still shows, and A's list would
    go under B."""
    amex = serve(list_ms=7000, address_moves_first=True)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    assert panel_reads(out)["stopped"] == 1, folded(out)
    assert not [r for r in records(tmp_path, "discovery.json").values()
                if digits_of(r["account"]) == B["digits"]]
    assert saved(tmp_path) == {}


@pytest.mark.parametrize("never,saved_first", [(3, 2), (2, 0)],
                         ids=["on-the-way-to-the-second-card", "on-the-way-to-the-first-card"])
def test_a_stop_at_a_switch_leaves_nothing_for_a_resume_to_take(attached, serve, tmp_path, capsys,
                                                                monkeypatch, never, saved_first):
    """A download stops with the switcher on the next card and the old list
    still on show. The year-end summaries share a date, so a Resume that took
    the switcher's word saved the old card's summary as the new card's,
    Completed. Resume now saves nothing, and Run All, which goes through the
    waits, saves each card's own. The list never comes on the way to the first
    card too, where Run All's first card would otherwise be read on the
    switcher's word."""
    monkeypatch.setattr(site, "LINK_WAIT_MS", 1000)
    amex = serve(list_ms=300, list_ms_of={str(never): -1})
    their_tab(attached, amex)
    conf = config(tmp_path, attached)

    code, out = run_all(conf, capsys)
    result = panel_reads(out)
    assert (result["stopped"], result["list_not_read"]) == (1, 1), folded(out)
    assert "the card's statements did not open" in folded(out)
    assert "press Resume" not in folded(out)
    assert "Resume would only stop here again, so run Pilot or Run All" in folded(out)
    kept = saved(tmp_path)
    assert len(kept) == saved_first, kept
    served = list(amex.downloads)

    code, out = run_all(conf, capsys, "--resume")
    assert "so nothing was taken" in folded(out)
    assert panel_reads(out)["list_not_read"] == 1
    assert amex.downloads == served, "a Resume pressed a Download on a list it could not trust"
    assert saved(tmp_path) == kept

    code, out = run_all(conf, capsys)
    holds_each_cards_own(tmp_path, out)


def test_one_option_left_of_an_archive_filed_by_card_keeps_its_keys(attached, serve, tmp_path, capsys):
    """Two cards, and later a switcher with only one of them. That card is read
    under its label, so nothing it saved comes again, and what is new is named
    by card. The one-card way would save its whole history again unnamed."""
    conf = config(tmp_path, attached)
    their_tab(attached, serve())
    code, out = run_all(conf, capsys)
    assert len(saved(tmp_path)) == 4

    amex = serve(cards=[dict(A, dates=["2030-12-11"] + A["dates"])])
    their_tab(attached, amex)
    code, out = run_all(conf, capsys)

    assert amex.downloads == ["11111/st-2030-12-11.pdf"], (amex.downloads, folded(out))
    kept = saved(tmp_path)
    assert len(kept) == 5
    new = [r for r in kept.values() if r["date"] == "2030-12-11"]
    assert new[0]["account"] == "Alpha Card (11111)" and new[0]["card"] == "11111", new
    assert "Alpha Card (11111)" in new[0]["name"]
    assert all(r["account"] for r in records(tmp_path, "discovery.json").values())
    assert noted_whole(tmp_path) is True


def test_a_dialog_left_open_is_closed_before_the_switcher_is_read(attached, serve, tmp_path, capsys):
    """A run that stopped at the file type dialog left it open, and it covers
    the switcher. On main a person with one card just went on, so it is closed
    first, and the run reads as any other."""
    amex = serve(cards=[SOLO], dialog_left_open=True)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    holds_one_cards_archive(tmp_path)
    assert "could not be read" not in out
    assert noted_whole(tmp_path) is True
    assert panel_reads(out)["manual_review"] == 0


@pytest.mark.parametrize("where", ["prepend", "append"], ids=["before", "after"])
def test_a_hidden_copy_of_the_options_costs_one_card_nothing(attached, serve, tmp_path, capsys, where):
    """A hidden copy doubled the card's label, which stopped a run that works
    on main, or was first and read as a switcher with no card."""
    amex = serve(cards=[SOLO], option_copies=where)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    holds_one_cards_archive(tmp_path)
    assert noted_whole(tmp_path) is True
    assert panel_reads(out)["manual_review"] == 0


@pytest.mark.parametrize("where", ["prepend", "append"], ids=["before", "after"])
def test_a_hidden_copy_of_the_options_costs_two_cards_nothing(attached, serve, tmp_path, capsys, where):
    amex = serve(option_copies=where)
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    holds_each_cards_own(tmp_path, out)


@pytest.mark.parametrize("cards", [[SOLO], [A, B]], ids=["one-shown", "two-shown"])
def test_a_hidden_option_naming_another_card_stops_and_nothing_is_called_whole(
        attached, serve, tmp_path, capsys, cards):
    """A card in a collapsed group, say. It cannot be chosen, so leaving it out
    would be a quiet short list, and with one card shown it would go the
    one-card way. The run names it and stops before any card is read."""
    amex = serve(cards=cards, hidden_options=[dict(name="Business Card", digits="88888")])
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)
    said = folded(out)

    assert "Business Card (88888) could not be chosen in the card switcher" in said
    assert panel_reads(out)["stopped"] == 1, said
    assert noted_whole(tmp_path) is False
    assert records(tmp_path, "discovery.json") == {}
    assert saved(tmp_path) == {} and amex.downloads == []
    assert not [p for p in amex.pressed if p.startswith("option/")], amex.pressed


def test_a_hidden_option_whose_digits_cannot_be_read_counts_as_another_card(attached, serve, tmp_path,
                                                                            capsys):
    amex = serve(cards=[SOLO], hidden_options=[dict(name="Business Card", digits="")])
    their_tab(attached, amex)
    code, out = run_all(config(tmp_path, attached), capsys)

    assert "at least one card has no account number" in folded(out)
    assert panel_reads(out)["stopped"] == 1
    assert noted_whole(tmp_path) is False
    assert saved(tmp_path) == {} and amex.downloads == []
