"""A document whose own control the site has turned off is left for review
and the next run, and the run goes on, in every app that presses one.

The release review of 0.45.0 found it. pressing.press_once stopped the run
when Playwright's press did not go through because the control was not
enabled, and pressing.click did the same. The apps that find a document's
control by its role and its name find a turned off one too, since
Playwright's get_by_role does, so a grayed out Download for one document
had Playwright wait eight seconds and then stopped the run there. Every
later run stopped at that same document, and nothing after it was ever
downloaded.

Now such a control is not pressed, and nothing more is pressed for its
document. The press raises pressing.TurnedOff only once Playwright has said
nothing but that it waited and the control was not enabled, nothing that
could be a document came, and a fresh read finds the control on the page,
showing, turned off and with nothing over it, what holds a control drawn to
take no pointer not counting as over it. Where an app presses a document's
own control it catches that and leaves the document, which its run marks
for review and takes again on the next run. Anywhere else TurnedOff stops
the run as NotPressed did, and so does a turned off control that something
covers or that cannot be read. AT&T and E*TRADE can press more than one
control for a document, and a control turned off after one of them was
pressed stops the run as before, since that press may still bring a PDF.

The census finds the presses by what the code does. From every method of
an app that marks a document downloaded it follows every function, method
and module function it can reach, through self, the app's own modules and
every name it hands on, and in them every press through
paperpull_core.pressing. Each one catches pressing.TurnedOff around the
press or is named in STOPS with why a turned off control there should stop
the run. Every press that catches it is then driven in a real browser, the
app's own function on a page whose control is turned off. Every word and
number here is made up.
"""
import ast
import importlib
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from paperpull_core import pressing, testkit

REPO = Path(__file__).resolve().parents[2]
HELPERS = {"press_once", "click", "check"}

# Presses a document's download reaches that stop the run when their control
# is turned off, as every press did before. None of them is a document's own
# control, or something was pressed for the document already. Each is
# named by its app, its function, the press and the step it names, with how
# many presses there are of that, so another press added beside one is not
# taken for it.
STOPS = {
    ("adp", "open_tax_statement_check", "press_once", "open the identity check"): (1,
        "the Tax Statements card's View statement opens ADP's identity check for every "
        "tax form, and left as turned off the run would have the person answer a "
        "prompt that never shows"),
    ("amex", "goto_documents", "click", "open the statements page"): (2,
        "reaches the statements page every document is taken from, so a turned off "
        "link there would leave every document"),
    ("amex", "expand_sections", "click", "open a section"): (1,
        "opens a section of the statements page for every document in it"),
    ("amex", "close_file_type_dialog", "click", "close the file type dialog"): (1,
        "closes the dialog the document before left open, and a dialog that will not "
        "close covers every press after it"),
    ("amex", "_choose_pdf", "check", "choose the pdf"): (1,
        "the PDF choice in the dialog the document's own Download opened, so a press "
        "was made for the document already"),
    ("amex", "download_document", "click", "press the dialog download"): (1,
        "the dialog's own Download, once the row's Download opened the dialog, so a "
        "press was made for the document already"),
    ("bofa", "open_statements", "click", "expand the statements heading"): (1,
        "opens the Statements heading every statement's Download PDF link is drawn "
        "under, so a turned off heading would leave every statement"),
    ("bofa", "_press_and_hear", "click", "download a statement"): (1,
        "presses one statement's Download PDF link, once a run, to learn the call every "
        "statement's PDF is asked with, so a turned off link would leave every statement"),
    ("chasebusiness", "_press", "click", ""): (1,
        "one press site serves the four controls that reach a list, an account in the "
        "menu, Statements, the year picker and a year in it, so a turned off one "
        "would leave every statement after it"),
    ("coinbase", "_press_load_more", "click", "load more of the list"): (1,
        "a control of the whole list, read as showing and turned on before it is pressed, "
        "and a list shown in full leaves only the statement not shown"),
    ("coinbase", "open_card_list", "click", "open the credit card statements"): (1,
        "the Statements page's Credit Card tab reaches the list every card statement is "
        "taken from, so a turned off tab there would leave every card statement"),
    ("ibkr", "open_activity_dialog", "click", "open the Activity Statement dialog"): (1,
        "the Activity Statement row's Run opens the dialog every month's statement is "
        "made in, so a turned off Run would leave every statement"),
    ("ibkr", "download_document", "click", "press the download button"): (1,
        "the dialog's own Download PDF, once the row's Run opened the dialog and the "
        "month was chosen, so a press was made for the document already"),
    ("pge", "goto_page_number", "press_once", ""): (1,
        "the history's page picker, a step to the page a bill is on and every bill "
        "after it"),
    ("shelbycounty", "_press_next", "click", "page the table"): (1,
        "pages the billing and payment tables every receipt is listed from, read as "
        "turned on before it is pressed, so a turned off NEXT where the footer says more "
        "pages leaves the rest of the list unread"),
    ("spectrum", "open_mobile_list", "click", "open the Mobile statements"): (1,
        "Billing's Mobile Account Number link reaches the list every Mobile statement is "
        "taken from, so a turned off link there would leave every Mobile statement"),
    ("spectrum", "expand_statement", "click", "expand the Mobile statement"): (1,
        "the Mobile statement's own Expand All, read as turned on before it is pressed, "
        "once the statement's row was pressed, so a press was made for the document already"),
    ("treasurydirect", "_press_link", "click", ""): (1,
        "TreasuryDirect moves only by its own links, a top tab, a history, a tax year, "
        "the 1099 or Return, each a plain server-drawn link that is never turned off. One "
        "that is would be a page this app does not know, and every later document is "
        "reached through the same tabs"),
    ("wellsfargo", "goto_documents", "click", "open the statements page"): (1,
        "the page's own Statements & Documents link reaches the page every document is "
        "taken from, so a turned off link there would leave every document"),
    ("wellsfargo", "_open_menu", "click", "open the menu"): (1,
        "the page's Menu button, opened only when no Statements & Documents link shows, "
        "to show the one it holds, so a turned off menu would leave every document"),
    ("wellsfargo", "_open_accounts_menu", "click", "open the accounts menu"): (1,
        "the top bar's Accounts button, opened only when no Statements & Documents link "
        "shows and no Menu button was opened, to show the one its menu holds, so a turned "
        "off button would leave every document"),
    ("wellsfargo", "open_statements", "click", "open the statements section"): (1,
        "the heading of the section every statement is listed in, pressed only when it "
        "says it is closed, so a turned off heading would leave every statement"),
    ("wellsfargo", "_open_picker", "click", "open the account picker"): (1,
        "the account picker every account's statements are chosen through, so a turned "
        "off picker would leave every statement of the other accounts"),
    ("wellsfargo", "choose_account", "click", "choose the account"): (1,
        "an account's entry in the picker, a step to that account's list and every "
        "statement in it"),
    ("vanguard", "dismiss_timeout", "click", "continue the session"): (1,
        "keeps the session open for every document"),
    ("vanguard", "show_more", "click", "show more of the list"): (1,
        "a control of the whole list, read as turned on before it is pressed, and a "
        "list shown in full leaves only the statement not shown"),
}

# The presses that catch TurnedOff and leave their document, by app, before
# this census. It finds them by what they do, this only keeps it from
# passing on finding none.
LEAVES = {
    ("alpaca", "_press"), ("amex", "download_document"), ("bilt", "_press"),
    ("amfam", "_catch_pdf"), ("applecard", "_catch_pdf"), ("att", "_catch_pdf"),
    ("chasebusiness", "_press_row"), ("coinbase", "_catch_statement"),
    ("coinbase", "_press_card_pdf"), ("firsthorizon", "_press"),
    ("etrade", "_catch_pdf"), ("golden1", "_catch_pdf"), ("nelnet", "_catch_pdf"),
    ("newrez", "_catch_pdf"), ("pge", "_press_once"), ("sba", "_catch_pdf"),
    ("simmons", "_catch_document"), ("smud", "_catch_pdf"), ("statefarm", "_catch_pdf"),
    ("vanguard", "download_document"),
    ("venmo", "show_all"), ("wellsfargo", "_catch_pdf")}


# ---------------------------------------------------------------------------
# The census, by what the code does
# ---------------------------------------------------------------------------

def _modules(app: Path) -> dict:
    out = {}
    for path in sorted(app.glob("*.py")):
        try:
            out[path.stem] = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            pass
    return out


def _is_true(n) -> bool:
    return isinstance(n, ast.Constant) and n.value is True


def _marks_downloaded(fn) -> bool:
    """Whether a function marks a document or a receipt downloaded, which
    is what the method that takes one does, as an attribute, a key of a
    record or a keyword."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and _is_true(n.value) and any(
                (isinstance(t, ast.Attribute) and t.attr == "downloaded_ok")
                or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and t.slice.value == "downloaded_ok") for t in n.targets):
            return True
        if isinstance(n, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "downloaded_ok" and _is_true(v)
                for k, v in zip(n.keys, n.values)):
            return True
        if isinstance(n, ast.keyword) and n.arg == "downloaded_ok" and _is_true(n.value):
            return True
    return False


class _App:
    """An app's modules, what each one's names point to, and every press
    through paperpull_core.pressing that a document's download reaches."""

    def __init__(self, app: Path):
        self.name = app.name
        self.mods = _modules(app)
        self.funcs, self.methods, self.mod_alias, self.name_alias = {}, {}, {}, {}
        self.press_alias, self.pressing = {}, {}
        for m, tree in self.mods.items():
            self.funcs[m] = {n.name: n for n in tree.body
                             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            self.methods[m] = {}
            for c in tree.body:
                if isinstance(c, ast.ClassDef):
                    for n in c.body:
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.methods[m].setdefault(n.name, []).append(("%s.%s" % (c.name, n.name), n))
            self.mod_alias[m], self.name_alias[m] = {}, {}
            self.press_alias[m], self.pressing[m] = {}, set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name in self.mods:
                            self.mod_alias[m][a.asname or a.name] = a.name
                        if a.name.split(".")[-1] == "pressing":
                            self.pressing[m].add(a.asname or a.name)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    if n.module in self.mods:
                        for a in n.names:
                            self.name_alias[m][a.asname or a.name] = (n.module, a.name)
                    if n.module.split(".")[-1] == "pressing":
                        for a in n.names:
                            if a.name in HELPERS:
                                self.press_alias[m][a.asname or a.name] = a.name
                    for a in n.names:
                        if a.name == "pressing":
                            self.pressing[m].add(a.asname or "pressing")
        self.starts = [(m, qual, fn) for m in self.mods for defs in self.methods[m].values()
                       for qual, fn in defs if _marks_downloaded(fn)]
        self.presses = self._reach()

    def _helper(self, m: str, call: ast.Call) -> str:
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in HELPERS and isinstance(f.value, ast.Name) \
                and f.value.id in self.pressing[m]:
            return f.attr
        if isinstance(f, ast.Name) and f.id in self.press_alias[m]:
            return self.press_alias[m][f.id]
        return ""

    def _points_to(self, m: str, n) -> list:
        out = []
        if isinstance(n, ast.Name):
            if n.id in self.funcs[m]:
                out.append((m, n.id, self.funcs[m][n.id]))
            if n.id in self.name_alias[m]:
                mm, name = self.name_alias[m][n.id]
                if name in self.funcs.get(mm, {}):
                    out.append((mm, name, self.funcs[mm][name]))
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id in ("self", "cls"):
                out.extend((m, qual, d) for qual, d in self.methods[m].get(n.attr, []))
            elif n.value.id in self.mod_alias[m]:
                mm = self.mod_alias[m][n.value.id]
                if n.attr in self.funcs.get(mm, {}):
                    out.append((mm, n.attr, self.funcs[mm][n.attr]))
        return out

    def _reach(self) -> list:
        seen, queue, presses = set(), list(self.starts), []
        while queue:
            m, qual, fn = queue.pop()
            if (m, qual) in seen:
                continue
            seen.add((m, qual))
            parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and self._helper(m, n):
                    step = next((k.value.value for k in n.keywords
                                 if k.arg == "step" and isinstance(k.value, ast.Constant)), "")
                    presses.append({"app": self.name, "module": m, "function": qual,
                                    "helper": self._helper(m, n), "step": step,
                                    "line": n.lineno, "leaves": self._caught(m, n, parents, fn)})
                for target in self._points_to(m, n):
                    if (target[0], target[1]) not in seen:
                        queue.append(target)
        return sorted(presses, key=lambda p: (p["module"], p["line"]))

    def _caught(self, m: str, call, parents: dict, fn) -> bool:
        """Whether the press sits in the body of a try, in its own function,
        with a handler for pressing.TurnedOff."""
        child, node = call, parents.get(call)
        while node is not None and node is not fn:
            if isinstance(node, ast.Try) and any(child is s for s in node.body):
                for h in node.handlers:
                    kinds = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
                    if any(isinstance(k, ast.Attribute) and k.attr == "TurnedOff"
                           and isinstance(k.value, ast.Name) and k.value.id in self.pressing[m]
                           for k in kinds):
                        return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return False
            child, node = node, parents.get(node)
        return False


APPS = [_App(d) for d in sorted((REPO / "apps").iterdir())
        if d.is_dir() and not d.name.startswith(("_", "."))]
PRESSES = [p for a in APPS for p in a.presses]
LEAVING = sorted({(p["app"], p["function"]) for p in PRESSES if p["leaves"]})
# Driven in a browser, every press that leaves its document and every one
# known to, so a press that stopped leaving still fails there.
DRIVEN = sorted(set(LEAVING) | LEAVES)


def test_every_app_that_takes_documents_is_read():
    """Not vacuous. The method that takes one document or one receipt is
    found in every app, by what it does."""
    entry = {a.name for a in APPS if any(m.endswith(("_docs", "_receipts")) for m in a.mods)}
    missing = sorted(a.name for a in APPS if a.name in entry and not a.starts)
    assert len(entry) >= 55 and not missing, missing


def _stop_key(p) -> tuple:
    return (p["app"], p["function"], p["helper"], p["step"])


def test_every_press_a_document_reaches_leaves_it_or_says_why_it_stops():
    unnamed = ["%(app)s %(module)s.%(function)s line %(line)d, %(helper)s step %(step)r" % p
               for p in PRESSES if not p["leaves"] and _stop_key(p) not in STOPS]
    assert not unnamed, (
        "these presses are reached from a document's download and neither catch "
        "pressing.TurnedOff nor are named in STOPS: %s" % unnamed)


def test_the_presses_named_to_stop_are_there_as_many_times_as_named():
    there: dict = {}
    for p in PRESSES:
        if not p["leaves"]:
            there[_stop_key(p)] = there.get(_stop_key(p), 0) + 1
    wrong = {key: (count, there.get(key, 0)) for key, (count, _why) in STOPS.items()
             if there.get(key, 0) != count}
    assert not wrong, "named, then found: %s" % wrong


def test_every_document_control_known_to_be_pressed_leaves_its_document():
    assert set(LEAVING) >= LEAVES, sorted(LEAVES - set(LEAVING))


# ---------------------------------------------------------------------------
# Each press that leaves its document, driven in a real browser
# ---------------------------------------------------------------------------

sync_api = pytest.importorskip("playwright.sync_api")

_PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 40

# Another document's control, drawn the moment the press is over, the way a
# list goes on drawing. A capture that went on looking for a second step
# would press it.
LATER = ("() => { const b = document.createElement('button'); b.type = 'button'; "
         "b.textContent = 'Download PDF'; b.onclick = () => { window.laterPresses++; }; "
         "document.body.appendChild(b); }")

COVER = ('<div style="position: fixed; left: 0; top: 0; width: 100vw; height: 100vh; '
         'z-index: 10; background: rgba(0, 0, 0, .25)" onclick="window.coverPresses++">'
         'Chat with us</div>')

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Statements</title>
<style>html, body { margin: 0; font: 16px sans-serif; }
td { height: 64px; position: relative; }
.ctl { display: inline-block; width: 220px; height: 40px; }</style>
<script>window.presses = 0; window.laterPresses = 0; window.coverPresses = 0;</script></head>
<body><main><h1>Statements</h1>
<table><tr><td>%(row)s</td><td>%(control)s</td></tr></table></main>%(extra)s</body></html>"""

# Vanguard's statement, as its own browser test makes it up.
VG_ACCOUNT = "Example Holder, Cash Plus Account, 1234567"


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        path = urlsplit(self.path).path
        extra = []
        if path.startswith(("/statement.pdf", "/doc")):
            self.server.asked.append(path)
            body, kind = _PDF, "application/pdf"
            extra = [("Content-Disposition", 'attachment; filename="statement.pdf"')]
        else:
            body, kind = self.server.page.encode("utf-8"), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _loaded(app: str, module: str):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_site", "_docs")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(REPO / "apps" / app))
    try:
        importlib.import_module("storage")
        return importlib.import_module(module)
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        yield b
        b.close()


class _Ran:
    """What one drive of an app's own press path came to."""

    def __init__(self, page, server):
        self.page = page
        self.server = server
        self.result = None
        self.stop = None
        self.waits: list = []
        self.trace: list = []

    def count(self, name: str) -> int:
        return int(self.page.evaluate("window.%s" % name))


# Playwright's word for a press that waited its whole time for its control
# to be turned on, which every drive here makes once, on the press's own
# time.
_PRESS_RAN_OUT = re.compile(r"(Locator|ElementHandle)\.click: Timeout \d+ms exceeded")


@pytest.fixture()
def drive(browser, tmp_path, monkeypatch):
    """Run `call(site, page, out, staging, trace)` on a page of the test's
    own site, with the press given half a second, the control drawn by
    `control`. `before` runs just before every press_once, and LATER is
    drawn as each one ends. The waits the call takes, counted rather than
    timed (testkit.Waits), are in `waits`."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.asked = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    context = browser.new_context(viewport={"width": 1000, "height": 600}, accept_downloads=True)
    monkeypatch.setattr(pressing, "PRESS_MS", 500)
    real = pressing.press_once
    real_click = pressing.click
    waits = testkit.Waits(monkeypatch)

    def run(app, module, call, *, row="June 30, 2026", control, extra="", before=None,
            press_ms=None):
        site = _loaded(app, module)
        monkeypatch.setattr(site, "is_safe_url", lambda url: (
            urlsplit(url or "").hostname == "127.0.0.1" and urlsplit(url).port == port))
        if press_ms:
            monkeypatch.setattr(pressing, "PRESS_MS", press_ms)
        httpd.page = PAGE % {"row": row, "control": control, "extra": extra}
        page = context.new_page()
        page.goto("http://127.0.0.1:%d/statements" % port)
        ran = _Ran(page, httpd)

        def with_later(*args, **kwargs):
            if before is not None:
                page.evaluate(before)
            try:
                return real(*args, **kwargs)
            finally:
                page.evaluate(LATER)

        def click_with_later(*args, **kwargs):
            try:
                return real_click(*args, **kwargs)
            finally:
                page.evaluate(LATER)
        monkeypatch.setattr(pressing, "press_once", with_later)
        monkeypatch.setattr(pressing, "click", click_with_later)
        out = tmp_path / app / "2026-06-30 Statement.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        staging = tmp_path / app / "downloads"
        staging.mkdir(exist_ok=True)
        with waits.counted() as ran.waits:
            try:
                ran.result = call(site, page, out, staging, ran.trace)
            except pressing.Stop as stop:
                ran.stop = stop
        ran.out = out
        monkeypatch.setattr(pressing, "press_once", real)
        monkeypatch.setattr(pressing, "click", real_click)
        return ran

    yield run
    context.close()
    httpd.shutdown()
    httpd.server_close()


def _button(off: bool, words: str = "Download statement", **attrs) -> str:
    more = "".join(' %s="%s"' % (k.replace("_", "-"), v) for k, v in attrs.items())
    return ('<button id="get" type="button" class="ctl"%s%s '
            'onclick="window.presses++; fetch(\'/statement.pdf\');">%s</button>'
            % (" disabled" if off else "", more, words))


def _catch_pdf(site, page, out, staging, trace):
    return site._catch_pdf(page, page.query_selector("#get"), "Download statement", out, trace,
                           staging)


def _amex(site, page, out, staging, trace):
    return site.download_document(page, "Statement", "2026-06-30", out)


def _vanguard(monkeypatch):
    def call(site, page, out, staging, trace):
        monkeypatch.setattr(site, "ensure_statements", lambda page: True)
        monkeypatch.setattr(site, "EVENT_WAIT_MS", 3000)
        return site.download_document(
            page, account_id="123400000000001", charitable=False, doc_type="Statement",
            title="Account Statement - " + VG_ACCOUNT, date="2026-08-31", out_path=out,
            dl_dir=staging)
    return call


def _coinbase(site, page, out, staging, trace):
    return site._catch_statement(page, staging, "June 2026", out, trace)


def _coinbase_card(site, page, out, staging, trace):
    """A Coinbase One Card statement's row PDF button, pressed as its own
    press path presses it, by its row's month."""
    return site._press_card_pdf(page, "June 2026", trace)


def _coinbase_card_button(off: bool) -> str:
    return ('<button id="get" type="button" class="ctl"%s '
            'onclick="window.presses++; fetch(\'/statement.pdf\');">PDF</button>'
            % (" disabled" if off else ""))


def _pge(site, page, out, staging, trace):
    said: dict = {}
    got = site._press_once(page, page.query_selector("#get"), lambda: False, said=said)
    trace.append(said)
    return got


def _alpaca(monkeypatch):
    """Alpaca's row Download, pressed through its own capture of the
    document's link and download. Only the Live account's check is stood
    in for, since the page is not on Alpaca's host. A turned off Download
    leaves the document for the next run (DocumentTurnedOff), which its
    run records nowhere and goes on from."""
    def call(site, page, out, staging, trace):
        monkeypatch.setattr(site, "check_live", lambda page, state: None)
        try:
            return site._catch_document(page, site.Run(), staging, 1, ALPACA_DOC, "2026-06-30",
                                        "trade_confirmation", out, trace)
        except site.DocumentTurnedOff:
            return False
    return call


ALPACA_DOC = "0f0f0f0f-1234-4abc-8def-0123456789ab"


def _alpaca_download(off: bool) -> str:
    return ('<p id="get" class="ctl" role="button"%s onclick="window.presses++; '
            'fetch(\'/statement.pdf\');">Download</p>'
            % (' aria-disabled="true"' if off else ""))


def _chasebusiness(site, page, out, staging, trace):
    """A statement's save menu, pressed as the row's own press path presses
    it, with the date the row reads."""
    return site._press_row(page, page.locator("#get"), css="#get",
                           what="the statement's save menu", guard=site.is_save_menu,
                           expect="Jun 30, 2026", step="open the save menu", run=site.Run())


def _chasebusiness_menu(off: bool) -> str:
    return ('<a id="get" class="ctl" href="#"%s onclick="window.presses++; return false;">'
            'Jun 30, 2026 Opens menu to save document</a>'
            % (' aria-disabled="true"' if off else ""))


def _vanguard_icon(off: bool) -> str:
    return ('<a id="get" class="ctl" title="Pdf download icon" href="/doc"%s '
            'onclick="window.presses++" aria-label="Download a pdf statement generated on '
            'August 31, 2026 with description %s">pdf</a>'
            % (' aria-disabled="true"' if off else "", VG_ACCOUNT))


def _amex_button(off: bool) -> str:
    return ('<button id="get" type="button" class="ctl" '
            'data-testid="card/2026-06-30/download-button"%s '
            'onclick="window.presses++">Download</button>' % (" disabled" if off else ""))


def _coinbase_button(off: bool) -> str:
    return ('<button id="get" type="button" class="ctl" data-testid="statements-pdf-v2"%s '
            'onclick="window.presses++; fetch(\'/statement.pdf\');">PDF</button>'
            % (" disabled" if off else ""))


def _shelbycounty(site, page, out, staging, trace):
    return site._press_for_blob(page, page.locator("#get"), "Print Receipt", out, trace)


def _shelbycounty_link(off: bool) -> str:
    return ('<a id="get" class="ctl" href="#"%s onclick="window.presses++; return false;">'
            'Print Receipt</a>' % (' aria-disabled="true"' if off else ""))


def _spectrum(site, page, out, staging, trace):
    entry = site.Entry(family="current", date="2026-06-30", statement_id="made-up-0001")
    return site._press_for_statement(page, page.locator("#get"), entry, [entry], out, staging, trace,
                                     lambda url: True)


def _spectrum_choose(monkeypatch):
    def call(site, page, out, staging, trace):
        entry = site.Entry(family="current", date="2026-06-30", statement_id="made-up-0001")
        monkeypatch.setattr(site, "STATEMENT_ROW", "#get")
        monkeypatch.setattr(site, "row_for", lambda page, e, entries: (0, "Statement June 30, 2026", ""))
        return site.choose_in_page(page, entry, [entry], staging, trace)
    return call


def _spectrum_mobile(monkeypatch):
    def call(site, page, out, staging, trace):
        monkeypatch.setattr(site, "MOBILE_ROW", "#get")
        return site.choose_mobile(page, 0, "Statement June 30, 2026", "2026-06-30", staging, trace)
    return call


def _spectrum_row(off: bool) -> str:
    return ('<a id="get" class="ctl" href="javascript:void(0);"%s onclick="window.presses++">'
            'Statement June 30, 2026</a>' % (' aria-disabled="true"' if off else ""))


def _spectrum_button(off: bool) -> str:
    return _button(off, "View Printable Statement")


def _pge_link(off: bool) -> str:
    return ('<a id="get" class="ctl" href="#"%s onclick="window.presses++; return false;">'
            'View Bill PDF</a>' % (' aria-disabled="true"' if off else ""))


def _firsthorizon(site, page, out, staging, trace):
    """First Horizon's capture on the bound card, the only card on the page.
    Its one press site, _press, serves the card's Download PDF here."""
    run = site.Run()
    run.attach(page.context)
    return site._catch_statement(page, run, staging, site.Target("acc", 0, "/statement.pdf"),
                                 "2026-06-30", out, trace)


def _firsthorizon_card(off: bool) -> str:
    return ('<div id="acc"><div class="card edocs-item-card" '
            'aria-label="Monthly statement for 06/30/2026"><button id="get" type="button" '
            'class="ctl edocs-download-btn" aria-label="Open New Tab to Download PDF for '
            '06/30/2026 statement"%s onclick="window.presses++; fetch(\'/statement.pdf\');">'
            'Download PDF</button></div></div>' % (" disabled" if off else ""))


def _bilt(site, page, out, staging, trace):
    """Bilt's capture on the bound statement, the only statement button on
    the page. Its one press site, _press, serves the statement's own button
    here, with the browser's downloads staged as a run stages them."""
    run = site.Run(staged=True)
    run.attach(page.context)
    target = site.Target("2026-06-30", "st-0001", "0f0f0f0f-1234-4abc-8def-0123456789ab", "4321")
    return site._catch_statement(page, run, target, out, trace)


def _bilt_button(off: bool) -> str:
    return ('<button id="get" type="button" class="ctl" aria-label="Download statement for '
            'June 30, 2026"%s onclick="window.presses++; fetch(\'/statement.pdf\');">'
            'June 30, 2026</button>' % (" disabled" if off else ""))


SIMMONS_ROW = "Loan Periodic Statement June 2026 Statement, RE ARM 00000000 (x0000)"


def _simmons(site, page, out, staging, trace):
    """Simmons Bank's capture on the bound row, the only document row on the
    page, its button inside its list item as Banno draws it."""
    target = site.Target(SIMMONS_ROW, "11111111-aaaa-4bbb-8ccc-000000000001", "statement.pdf",
                         "0a1b2c3d-1111-4222-8333-944455556666")
    return site._catch_document(page, site.Run(), staging, target, out, trace)


def _simmons_row(off: bool) -> str:
    return ('<jha-list-item role="listitem"><button id="get" type="button" class="ctl"%s '
            'onclick="window.presses++; fetch(\'/statement.pdf\');">%s</button></jha-list-item>'
            % (" disabled" if off else "", SIMMONS_ROW))


VENMO_PROFILE = "1234567890123456"


def _venmo(site, page, out, staging, trace):
    """Venmo's month, its first rows drawn and its own Show more under
    them, drawn whole through show_all before the month is printed. The
    page is at the month's own statement address, without a load. A turned
    off Show more leaves the month for review (ListStopped), which its
    download records and goes on from."""
    page.evaluate("(to) => history.replaceState(null, '', to)",
                  "/statement?accountType=personal&month=6&profileId=%s&year=2026" % VENMO_PROFILE)
    try:
        return site.show_all(page, site.Where("personal", VENMO_PROFILE), "2026-06",
                             site._month_heard("2026-06"))
    except site.ListStopped:
        return False


# The month picker and the statement's heading, beside the list.
VENMO_MONTH = '<input type="text" value="June 2026"><h2>Account Statement</h2>'


def _venmo_list(off: bool) -> str:
    return ('<div class="completedTransactionList_q1"><a class="transactionItem_q2" href="#">'
            '<span data-testid="money">-$1.00</span></a><div><button id="get" type="button" '
            'class="ctl"%s onclick="window.presses++">Show more</button></div></div>'
            % (" disabled" if off else ""))


def _how(app: str, function: str, monkeypatch):
    """The app's own press path, the page that shows its control, and the
    row it sits in, for each press that leaves its document."""
    if function == "_catch_pdf":
        return "%s_site" % app, _catch_pdf, _button, "June 30, 2026"
    if (app, function) == ("alpaca", "_press"):
        return "alpaca_site", _alpaca(monkeypatch), _alpaca_download, \
            "2026-06-30</td><td>trade_confirmation"
    if (app, function) == ("amex", "download_document"):
        return "amex_site", _amex, _amex_button, "June 30, 2026"
    if (app, function) == ("bilt", "_press"):
        return "bilt_site", _bilt, _bilt_button, "Statements"
    if (app, function) == ("vanguard", "download_document"):
        return "vanguard_site", _vanguard(monkeypatch), _vanguard_icon, \
            "%s</td><td>08/31/2026" % VG_ACCOUNT
    if (app, function) == ("chasebusiness", "_press_row"):
        return "chasebusiness_site", _chasebusiness, _chasebusiness_menu, "Jun 30, 2026"
    if (app, function) == ("coinbase", "_catch_statement"):
        return "coinbase_site", _coinbase, _coinbase_button, "June 2026"
    if (app, function) == ("coinbase", "_press_card_pdf"):
        return "coinbase_site", _coinbase_card, _coinbase_card_button, "June 2026"
    if (app, function) == ("firsthorizon", "_press"):
        return "firsthorizon_site", _firsthorizon, _firsthorizon_card, "06/30/2026"
    if (app, function) == ("pge", "_press_once"):
        return "pge_site", _pge, _pge_link, "June 30, 2026"
    if (app, function) == ("simmons", "_catch_document"):
        return "simmons_site", _simmons, _simmons_row, "June 30, 2026"
    if (app, function) == ("shelbycounty", "_press_for_blob"):
        return "shelbycounty_site", _shelbycounty, _shelbycounty_link, "06/30/2026"
    if (app, function) == ("spectrum", "_press_for_statement"):
        return "spectrum_site", _spectrum, _spectrum_button, "June 30, 2026"
    if (app, function) == ("spectrum", "choose_in_page"):
        return "spectrum_site", _spectrum_choose(monkeypatch), _spectrum_row, "June 30, 2026"
    if (app, function) == ("spectrum", "choose_mobile"):
        return "spectrum_site", _spectrum_mobile(monkeypatch), _spectrum_row, "June 30, 2026"
    if (app, function) == ("venmo", "show_all"):
        return "venmo_site", _venmo, _venmo_list, VENMO_MONTH
    return None


def test_every_press_that_leaves_its_document_is_driven_here(monkeypatch):
    undriven = [x for x in DRIVEN if _how(x[0], x[1], monkeypatch) is None]
    assert not undriven, "no browser drive for %s, add one to _how" % undriven


@pytest.mark.parametrize("app,function", DRIVEN, ids=lambda x: x)
def test_a_turned_off_control_is_not_pressed_and_the_run_goes_on(drive, app, function,
                                                                 monkeypatch):
    module, call, control, row = _how(app, function, monkeypatch)
    ran = drive(app, module, call, row=row, control=control(True))
    assert ran.stop is None, "the run stopped at a turned off control: %r" % (ran.stop,)
    assert not ran.result, "the press path took the document: %r" % (ran.result,)
    assert ran.count("presses") == 0, "the turned off control was pressed"
    assert ran.count("laterPresses") == 0, "a control drawn after the press was pressed"
    assert ran.server.asked == [], "something was asked for the document"
    assert not ran.out.exists()
    # Left once the press's own time is over, not after a capture's waits
    # for a document, which take ten seconds and more. The one wait taken
    # is the press itself, Playwright waiting out the press's own time for
    # the control to be turned on. The waits are counted, not timed, since
    # a slow machine once took 54 s over this drive with no other wait.
    assert len(ran.waits) == 1 and _PRESS_RAN_OUT.match(ran.waits[0].what), ran.waits


# Bootstrap and Material UI draw a turned off control so it takes no
# pointer, so what is at its point is what holds it.
TAKES_NO_POINTER = "<style>#get { pointer-events: none; }</style>"


@pytest.mark.parametrize("app,function", DRIVEN, ids=lambda x: x)
def test_a_turned_off_control_drawn_to_take_no_pointer_is_left_too(drive, app, function,
                                                                  monkeypatch):
    module, call, control, row = _how(app, function, monkeypatch)
    ran = drive(app, module, call, row=row, control=control(True), extra=TAKES_NO_POINTER)
    assert ran.stop is None, "the run stopped at a turned off control: %r" % (ran.stop,)
    assert not ran.result
    assert ran.count("presses") == 0 and ran.count("laterPresses") == 0
    assert ran.server.asked == []


@pytest.mark.parametrize("app,function", DRIVEN, ids=lambda x: x)
def test_a_turned_off_control_under_a_cover_stops_the_run(drive, app, function, monkeypatch):
    module, call, control, row = _how(app, function, monkeypatch)
    ran = drive(app, module, call, row=row, control=control(True), extra=COVER)
    assert isinstance(ran.stop, pressing.Covered), ran.stop
    assert ran.count("presses") == 0
    assert ran.count("coverPresses") == 0


def _keeps_presses(app: str) -> bool:
    """Whether the app's capture keeps one list of what was pressed for a
    document, as an app that presses more than one control for one does."""
    import inspect
    site = _loaded(app, "%s_site" % app)
    return "pressed" in inspect.signature(site._catch_pdf).parameters


KEEPS_PRESSES = sorted(a for a, f in DRIVEN if f == "_catch_pdf" and _keeps_presses(a))


def test_the_apps_that_press_more_than_one_control_for_a_document_keep_the_list():
    assert {"att", "etrade"} <= set(KEEPS_PRESSES), KEEPS_PRESSES


@pytest.mark.parametrize("app", KEEPS_PRESSES)
def test_a_control_turned_off_after_a_press_for_its_document_stops_the_run(drive, app):
    """Something was pressed for the document already and brought nothing
    yet. What it began may still bring a PDF, which would reach the next
    document's capture, so the run stops there as it always did."""
    def call(site, page, out, staging, trace):
        return site._catch_pdf(page, page.query_selector("#get"), "Download statement", out,
                               trace, staging, ["Download PDF"])
    ran = drive(app, "%s_site" % app, call, control=_button(True))
    assert isinstance(ran.stop, pressing.TurnedOff), ran.stop
    assert ran.count("presses") == 0


@pytest.mark.parametrize("app", KEEPS_PRESSES)
def test_a_press_that_brought_nothing_is_counted_for_its_document(drive, app):
    """The document's control is pressed and brings nothing, and the page
    then turns it off, the way a site can while it works on the press. The
    second try stops the run, since the first press may still bring a PDF.
    Every wait of the capture is a moment here."""
    pressed: list = []

    def call(site, page, out, staging, trace):
        own_wait = page.wait_for_timeout
        page.wait_for_timeout = lambda ms: own_wait(min(ms, 20))
        first = site._catch_pdf(page, page.query_selector("#get"), "Download statement", out,
                                trace, staging, pressed)
        page.evaluate("document.getElementById('get').disabled = true")
        return first, site._catch_pdf(page, page.query_selector("#get"), "Download statement",
                                      out, trace, staging, pressed)
    ran = drive(app, "%s_site" % app, call, control=(
        '<button id="get" type="button" class="ctl" onclick="window.presses++">'
        'Download statement</button>'))
    assert isinstance(ran.stop, pressing.TurnedOff), (ran.stop, ran.result, pressed)
    assert ran.count("presses") == 1
    assert pressed[0] == "Download statement", "the first press was not counted: %r" % pressed


@pytest.mark.parametrize("app", KEEPS_PRESSES)
def test_a_turned_off_first_control_is_marked_so_nothing_more_is_pressed(drive, app):
    pressed: list = []

    def call(site, page, out, staging, trace):
        return site._catch_pdf(page, page.query_selector("#get"), "Download statement", out,
                               trace, staging, pressed)
    ran = drive(app, "%s_site" % app, call, control=_button(True))
    assert ran.stop is None and ran.result is False
    site = _loaded(app, "%s_site" % app)
    assert pressed == [site._TURNED_OFF]


@pytest.mark.parametrize("app", sorted({a for a, f in DRIVEN if f == "_catch_pdf"}))
def test_a_control_turned_on_while_the_press_waits_is_pressed_once(drive, app):
    """The press still waits for a control the page turns on a moment
    later, as Playwright always did, and the statement it brings is saved."""
    ran = drive(app, "%s_site" % app, _catch_pdf, control=_button(True), press_ms=4000,
                before="() => setTimeout(() => { document.getElementById('get').disabled = "
                       "false; }, 300)")
    assert ran.stop is None, ran.stop
    assert ran.result is True
    assert ran.out.read_bytes() == _PDF
    assert ran.count("presses") == 1
