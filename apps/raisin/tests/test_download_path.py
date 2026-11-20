"""Raisin's real download path, run end to end without a browser.

0.34.0 shipped four apps that passed the capture a keyword it did not
take. This runs Raisin's own process() loop with the dashboard stood in for
(fake_raisin.FakePage) and the capture replaced by paperpull_core.testkit,
which holds every call to place() to its real signature.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import raisin_docs as app_mod
import raisin_site as site
from fake_raisin import FakePage, pdf_for
from paperpull_core import delivery, identity
from paperpull_core.testkit import StrictDelivery


@pytest.fixture
def app(monkeypatch, tmp_path):
    site._RUN.clear()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path),
                                  "min_pdf_bytes": 100}), encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config)])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    the_app = app_mod.App(args)
    page = FakePage()
    the_app._work_page = page
    monkeypatch.setattr(the_app, "page", lambda: page)
    monkeypatch.setattr(the_app, "_delay", lambda *a, **kw: None)
    the_app.cmd_discover(quiet=True)
    yield the_app, page
    site._RUN.clear()


def test_a_run_reaches_the_capture_with_arguments_it_accepts(app, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    the_app, page = app
    the_app.process(the_app._select())
    assert [c.name for c in spy.calls] == ["place"] * 3
    assert the_app.stats["failed"] == 0, "a call the capture refused"
    assert len(the_app.stats["new_files"]) == 3
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is True


def test_the_fetched_bytes_are_placed_under_the_title_alone(app, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    the_app, page = app
    docs = the_app._select()
    the_app.process(docs)
    for call, doc in zip(spy.calls, docs):
        args = call.arguments
        assert args["data"] == page.files[doc.document_id]
        assert args["expect"] == site.identity_for(doc)
        # Never a date for the core's check, whose dotted form reads month first.
        assert not args["expect"].date
        assert all(isinstance(r, identity.Identity) and not r.date for r in args["rivals"])
    assert Path(the_app.stats["new_files"][0]).read_bytes() in page.files.values()


def test_a_pdf_this_app_refuses_never_reaches_the_capture(app, monkeypatch):
    spy = StrictDelivery().install(monkeypatch)
    the_app, page = app
    page.files["d0001"] = pdf_for("05.03.2026", "Kontoauszug", issuer="Musterbank AG")
    the_app.process(the_app._select())
    assert len(spy.calls) == 2
    assert all(c.arguments["data"] != page.files["d0001"] for c in spy.calls)


def test_the_core_refusing_it_is_a_wrong_document_not_a_save(app, monkeypatch):
    StrictDelivery(outcome=delivery.WRONG).install(monkeypatch)
    the_app, _ = app
    the_app.process(the_app._select()[:1])
    assert the_app.stats["failed"] == 1 and the_app.stats["wrong_document"] == 1
    assert not the_app.stats["new_files"]


def test_nothing_placed_is_a_capture_failure_not_a_crash(app, monkeypatch):
    StrictDelivery(outcome=delivery.NOT_PLACED).install(monkeypatch)
    the_app, _ = app
    the_app.process(the_app._select()[:1])
    assert the_app.stats["failed"] == 1
    assert not the_app.stats["new_files"]
