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

Nothing here is used by a run. It is in the package so every app's tests
can import it the same way they import everything else.
"""
from __future__ import annotations

import inspect
import io
import json
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
