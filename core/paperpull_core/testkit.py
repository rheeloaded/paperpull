"""A stand-in for paperpull_core.delivery, for an app's own tests.

0.34.0 shipped four providers that failed every document. Each passed
deliver() a keyword it did not take, the call raised before anything was
pressed, and the app's loop counted it as an ordinary failure. Every one
of those apps' tests passed, because none of them ran the code that
makes the call. The tests that could have run it needed a browser and a
signed-in account.

This is what lets them run it without either. Installed in place of
deliver, place and render, it binds every call to the real function's
signature first, so a keyword the real one would refuse raises the same
TypeError here, in the test, instead of on somebody's account. Then it
writes a small real PDF to the path it was given and says the document
was saved, so the app goes on through everything it does after a
capture and that is exercised too.

    from paperpull_core.testkit import StrictDelivery

    def test_a_run_reaches_the_capture_and_saves(monkeypatch, tmp_path):
        spy = StrictDelivery().install(monkeypatch)
        app.process([doc])
        assert spy.calls and spy.calls[0].name == "deliver"

text_pdf is the other half, a PDF that says something, for a test of
whether a saved document names what it was saved as, and receipt_app and
file_a_receipt hand one to a receipt app's own check.

stall_reads makes chosen elements of a real page fail to answer, for a
test of what an app does with an element it could not read.

drawn_browser starts a browser with a debugging port for an app to attach
to, and hands it over only once a tab has drawn a page, since a browser
that has only just started can abort its first navigation.

Nothing here is used by a run. It is in the package so every app's tests
can import it the same way they import everything else.
"""
from __future__ import annotations

import inspect
import io
import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import delivery as _delivery

NAMES = ("deliver", "place", "render")

# The real functions, taken when this module is imported, before any test
# has had a chance to replace them.
_REAL = {name: getattr(_delivery, name) for name in NAMES}


def sample_pdf(min_bytes: int = 4000) -> bytes:
    """A one-page PDF that opens in pypdf and clears every app's minimum
    size, which is two to three thousand bytes."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Subject": "stand-in " + "x" * min_bytes})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def text_pdf(lines, min_bytes: int = 4000) -> bytes:
    """A one-page PDF whose lines pypdf reads back as text, for a test of
    what a saved receipt says rather than whether it is a PDF. Helvetica,
    so Latin-1 only, and padded past every app's minimum size."""
    def literal(line: str) -> str:
        return str(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "".join("BT /F1 11 Tf 40 %d Td (%s) Tj ET\n" % (760 - 16 * i, literal(line))
                     for i, line in enumerate(lines)).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out) + b" " * max(0, min_bytes - len(out))


def receipt_app(app_module, tmp_path, **config):
    """A receipt app's own App, built the way its main() builds it, with its
    output and browser profile under `tmp_path`. Nothing is opened."""
    cfg = Path(tmp_path) / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(Path(tmp_path) / "out"),
        "profile_dir": str(Path(tmp_path) / "profile"),
        "delay_min_seconds": 0, "delay_max_seconds": 0, **config}), encoding="utf-8")
    return app_module.App(app_module.build_parser().parse_args(["--config", str(cfg)]))


@dataclass
class Filed:
    kept: bool          # what _finish_pdf answered
    path: Path          # where the PDF is now
    record: dict        # the purchase's record in progress.json


def file_a_receipt(app, purchase, lines, listed=None) -> Filed:
    """Hand an app's own _finish_pdf a PDF reading `lines`, left where its
    capture would have left it, and say what became of it. `listed` is the
    purchase's row as the order list showed it, put where the app's
    discovery keeps it. There is no page, so a retry that prints the page
    again fails, as it does when the page has gone."""
    if listed is not None:
        app.discovery.update(purchase.key, dict(listed))
    out = app.paths.root / "Saved" / "receipt.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text_pdf(lines))
    # Most take the page first. Uber's has no page to print again.
    if next(iter(inspect.signature(app._finish_pdf).parameters)) == "page":
        kept = app._finish_pdf(None, purchase, out)
    else:
        kept = app._finish_pdf(purchase, out)
    return Filed(bool(kept), Path(purchase.pdf_path), app.progress.get(purchase.key) or {})


def stall_reads(monkeypatch, stalled, locator=("element_handle",), handle=(), scripts=()):
    """Reading an element whose data-guid is in `stalled` raises
    Playwright's TimeoutError, the way reads did on the stalled CI runner
    of run 36792330947, and every other read answers as it would.

    `locator` names the Locator methods that stall and `handle` the
    ElementHandle methods. When `scripts` is given, an evaluate of an
    element stalls only for those scripts, so the page's other questions
    about it still answer. The element is known by its own data-guid,
    read the way the page would give it, before the stalled read runs.
    A read of several elements at once, as all_inner_texts is, stalls
    when any one of them is stalled."""
    from playwright.sync_api import ElementHandle, Locator, TimeoutError as PlaywrightTimeout
    stalled = set(stalled)
    guid_of_locator = Locator.get_attribute
    guids_of_locator = Locator.evaluate_all
    guid_of_handle = ElementHandle.get_attribute

    def stalling(name, real, guid_of, is_locator):
        def read(self, *args, **kwargs):
            if scripts and name in ("evaluate", "evaluate_handle") \
                    and (args[0] if args else kwargs.get("expression")) not in scripts:
                return real(self, *args, **kwargs)
            try:
                guids = {guid_of(self, "data-guid", timeout=2000) if is_locator else guid_of(self, "data-guid")}
            except Exception:
                # A locator of several elements, which a read of one refuses.
                try:
                    guids = set(guids_of_locator(self, "els => els.map(e => e.getAttribute('data-guid'))")) \
                        if is_locator else set()
                except Exception:
                    guids = set()
            if guids & stalled:
                raise PlaywrightTimeout("Timeout exceeded, a stalled read (testkit.stall_reads).")
            return real(self, *args, **kwargs)
        return read
    for name in locator:
        monkeypatch.setattr(Locator, name, stalling(name, getattr(Locator, name), guid_of_locator, True))
    for name in handle:
        monkeypatch.setattr(ElementHandle, name, stalling(name, getattr(ElementHandle, name), guid_of_handle, False))


@dataclass
class Call:
    name: str
    arguments: dict


class StrictDelivery:
    """Stands in for deliver, place and render, held to their signatures.

    `outcome` is what every call reports, delivery.SAVED unless a test
    wants to see what the app does with something else. On SAVED the
    stand-in writes sample_pdf() to the path it was handed."""

    def __init__(self, outcome: str = _delivery.SAVED):
        self.outcome = outcome
        self.calls: list = []

    def install(self, monkeypatch) -> "StrictDelivery":
        for name in NAMES:
            monkeypatch.setattr(_delivery, name, self._fake(name))
        return self

    def _fake(self, name: str):
        signature = inspect.signature(_REAL[name])

        def fake(*args, **kwargs):
            # Raises TypeError for a keyword the real function does not
            # take, which is the whole point.
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            self.calls.append(Call(name, dict(bound.arguments)))
            if name == "deliver" and not isinstance(
                    bound.arguments.get("request"), _delivery.DocumentRequest):
                raise TypeError("deliver() was not handed a DocumentRequest")
            out = Path(bound.arguments["out_path"])
            if self.outcome == _delivery.SAVED:
                out.parent.mkdir(parents=True, exist_ok=True)
                data = bound.arguments.get("data") if name == "place" else None
                out.write_bytes(data if data else sample_pdf())
            return _delivery.Delivery(self.outcome, "stand-in")
        fake.__name__ = name
        return fake


class TabsHeardLate:
    """Playwright told of a new tab late, the way a busy machine tells it.

    A page knows it opened a tab the moment it asks for one, and Playwright
    hears of the tab some time after, once the browser has made it and
    Playwright has set it up. On a machine running three other full suites,
    the tab came only after an app had taken its document and closed the
    tabs its press opened, so it was never closed (2026-10-01). This holds
    back the message that tells Playwright of a new tab until let_through,
    so a test can put the tab's arrival after whichever step of the app it
    likes, the same way every time, however busy the machine is.

    It replaces Playwright's own message dispatch, a private part of it,
    for the test that installs it. `announced` counts the tabs it saw, so a
    test that finds none knows the hold no longer works, rather than
    passing without it."""

    def __init__(self, monkeypatch):
        from playwright._impl._connection import Connection

        self.announced = 0
        self.released = False
        self._held: list = []
        self._scheduled = False
        self._real = Connection.dispatch

        def dispatch(conn, msg):
            if msg.get("method") == "page" and str(msg.get("guid", "")).startswith("browser-context"):
                self.announced += 1
                if not self.released:
                    self._held.append((conn, msg))
                    return None
            return self._real(conn, msg)

        monkeypatch.setattr(Connection, "dispatch", dispatch)

    def let_through(self) -> None:
        """Every tab held so far reaches Playwright now, and a later one as
        it comes."""
        self.released = True
        while self._held:
            conn, msg = self._held.pop(0)
            self._real(conn, msg)

    def let_through_soon(self, page, seconds: float = 0.0) -> None:
        """At Playwright's next turn, the next time anything asks Playwright
        for anything, or `seconds` after. Only the first call counts."""
        if self._scheduled:
            return
        self._scheduled = True
        if seconds:
            page._loop.call_later(seconds, self.let_through)
        else:
            page._loop.call_soon(self.let_through)


# -- a browser to attach to, ready before the app attaches ---------------------

class FreshBrowserError(RuntimeError):
    """A fresh browser that never became ready, and what each start did."""


class NoDebugPort(FreshBrowserError):
    """The browser opened no debugging port at all."""


_READY_TITLE = "drawn before the app attaches"


class _ReadyPage:
    """One small page on a port of its own, for a fresh browser to draw."""

    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        body = ("<!doctype html><html><head><title>%s</title></head><body>ready</body></html>"
                % _READY_TITLE).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.address = "http://127.0.0.1:%d/" % self.httpd.server_address[1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _start_fresh_browser(exe, profile, args):
    """The browser as a program of its own with a debugging port, and its
    address, or None for the address when it opened no port."""
    import subprocess
    import time

    from .browser import wait_for_debug_port

    proc = subprocess.Popen(
        [str(exe), "--headless=new", "--remote-debugging-port=0",
         "--user-data-dir=%s" % profile, "--no-first-run", "--no-default-browser-check",
         *args, "about:blank"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port, deadline = "", time.monotonic() + 30
    while not port and time.monotonic() < deadline and proc.poll() is None:
        try:
            port = (Path(profile) / "DevToolsActivePort").read_text().split()[0]
        except (OSError, IndexError):
            time.sleep(0.1)
    if not port or not wait_for_debug_port(port):
        return proc, None
    return proc, "http://127.0.0.1:%s" % port


def _draws(url, address, tries):
    """Whether a tab opened the way an attaching app opens one, over CDP in
    the browser's own first context, draws the ready page, and what each try
    did. A tab that did not draw is left where it is, since closing a fresh
    browser's tab has hung before. The one that drew stays open on it."""
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    did = []
    with sync_playwright() as p:
        try:
            context = p.chromium.connect_over_cdp(url).contexts[0]
        except (PlaywrightError, IndexError) as e:
            return False, ["could not attach, %s" % str(e).splitlines()[0]]
        for _try in range(tries):
            try:
                page = context.new_page()
                page.goto(address, wait_until="domcontentloaded", timeout=15000)
                if page.title() == _READY_TITLE:
                    return True, did
                did.append("drew %r instead" % page.title())
            except PlaywrightError as e:
                did.append(str(e).splitlines()[0])
    return False, did


def _close_browser(proc, url) -> None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.connect_over_cdp(url).new_browser_cdp_session().send("Browser.close")
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
        proc.wait(timeout=15)


@contextmanager
def drawn_browser(exe, make_profile, args=(), starts=3, tries=3):
    """A browser started as a program of its own with a debugging port, the
    way login.bat starts one, and its address, handed over only once a tab
    has drawn a page. Closed when the block ends.

    At home login.bat opened the browser and the person signed in there,
    well before the app attached. A browser that has only just started is
    not that. On CI a fresh Chrome's first navigation came back
    net::ERR_ABORTED after about five seconds, which is how a browser
    answers when its network service restarts under it, and about one
    fresh start in thirteen loses its first tab. The GitHub, Walmart and
    Best Buy fixtures guard against it one by one (2026-10-01), and this is
    that guard in one place.

    A page of this helper's own, served on a port of its own, is opened in
    a new tab of the browser's first context, which is how an attaching
    app opens its tab, and again in another tab when it does not draw. A
    browser that never draws it is closed and another started. The tab that
    drew stays open on a page that asks for nothing more. make_profile is
    called once per start for an empty profile folder. NoDebugPort means
    the browser opened no port at all, FreshBrowserError that no start drew
    the page, naming what each one did."""
    ready = _ReadyPage()
    proc, url, tried = None, None, []
    try:
        for _start in range(starts):
            proc, url = _start_fresh_browser(exe, make_profile(), args)
            if url is None:
                proc.kill()
                proc.wait(timeout=15)
                proc = None
                raise NoDebugPort("the browser opened no debugging port")
            drew, did = _draws(url, ready.address, tries)
            if drew:
                break
            tried.append(", then ".join(did) or "nothing drew")
            proc.kill()
            proc.wait(timeout=15)
            proc = None
        else:
            raise FreshBrowserError("%d fresh browsers in a row never drew a page. %s"
                                    % (starts, " / ".join(tried)))
        yield url
    finally:
        if proc is not None:
            _close_browser(proc, url)
        ready.close()
