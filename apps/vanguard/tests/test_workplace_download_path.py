"""A workplace statement taken through Vanguard's own download path.

Discover and download_one run as a run runs them, on a stand-in workplace
page, with testkit.StrictDelivery standing in for delivery.place, so the
call the app makes is held to place's signature and what the app does with
each outcome is seen. Every plan and period is invented."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import vanguard_docs as docs
import vanguard_site as site
from paperpull_core import delivery
from paperpull_core import storage as core_storage
from paperpull_core.testkit import StrictDelivery, text_pdf
from test_workplace_statements import END, PLAN, WorkplacePage


@pytest.fixture
def run(tmp_path, monkeypatch):
    for name in ("_SPEC", "_FILENAME_PATTERN", "_PATTERN_OWNER", "_FILENAME_OWNER"):
        monkeypatch.setattr(core_storage, name, getattr(core_storage, name))
    app_dir = Path(docs.__file__).resolve().parent
    config = json.loads((app_dir / "config.example.json").read_text(encoding="utf-8"))
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0, "default_start_date": ""})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    page = WorkplacePage()
    page.pdf = {"0": text_pdf([f"Plan number {PLAN}", "January 1, 2032 through March 31, 2032"])}
    app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
    app.page = lambda: page
    app._work_page = page
    app.check_session = lambda *_a, **_kw: None
    app.cmd_discover(quiet=True)
    [doc] = [d for d in app._select() if d.date == END]
    return app, page, doc


def _take(app, page, doc):
    name = core_storage.build_pdf_filename(doc.date, doc.summary, "", record=doc)
    app.download_one(page, doc, name)
    return app.progress.get(doc.key) or {}


def test_a_workplace_statement_is_put_in_place_through_delivery(run, monkeypatch):
    app, page, doc = run
    strict = StrictDelivery().install(monkeypatch)
    record = _take(app, page, doc)
    assert [c.name for c in strict.calls] == ["place"]
    assert record["state"] == "Completed"
    assert Path(record["pdf_path"]).is_file()
    assert Path(record["pdf_path"]).parent == Path(strict.calls[0].arguments["out_path"]).parent


@pytest.mark.parametrize("outcome", [delivery.NOT_PLACED, delivery.NOT_A_PDF, delivery.NOTHING])
def test_a_place_that_did_not_save_leaves_nothing_and_the_statement_to_try_again(run, monkeypatch, outcome):
    app, page, doc = run
    strict = StrictDelivery(outcome).install(monkeypatch)
    record = _take(app, page, doc)
    assert [c.name for c in strict.calls] == ["place"]
    assert record["state"] == "Failed"
    assert not Path(strict.calls[0].arguments["out_path"]).exists()
