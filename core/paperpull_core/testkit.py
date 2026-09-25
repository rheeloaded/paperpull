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

Nothing here is used by a run. It is in the package so every app's tests
can import it the same way they import everything else.
"""
from __future__ import annotations

import inspect
import io
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
