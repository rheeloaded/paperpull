"""Diagnose that meets a stop at a press still writes what it saw.

Diagnose walks the history's pages, and a page is reached through the page
picker, whose option is pressed through paperpull_core.pressing.press_once.
A press it would not make, a covered option say, stops there. Diagnose is
what a tester runs to show what went wrong, so the walk ends, and the
detailed file and the survey are still written, the file saying why the
walk stopped, the way American Express's Diagnose does. Every word here is
made up.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import pge_docs
from paperpull_core import pressing


def test_diagnose_that_meets_a_stop_still_writes_its_files(tmp_path, monkeypatch, capsys):
    sync_api = pytest.importorskip("playwright.sync_api")
    example = Path(pge_docs.__file__).parent / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9"})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    app = pge_docs.App(pge_docs.build_parser().parse_args(["--config", str(cfg), "--diagnose"]))

    def walk_meets_a_cover(_page):
        raise pressing.Covered(
            "press a control", "something on the page is over the control",
            ["Something on the page covers the option for page 2, so nothing was pressed.",
             pressing.AGAIN], {"verdict": "covered", "error": "timeout"}, after_a_press=True)
    monkeypatch.setattr(pge_docs.site, "goto_documents", lambda _page: True)
    monkeypatch.setattr(pge_docs.site, "collect_download_docs", walk_meets_a_cover)
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip("no browser to drive: %s" % e)
        page = browser.new_page()
        page.set_content("<h1>Bill and payment history</h1>")
        app.page = lambda: page
        capsys.readouterr()
        app.cmd_diagnose()
        app.write_survey()
        browser.close()
    detailed = json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(
        encoding="utf-8"))
    assert detailed["stopped"] == {"step": "press a control",
                                   "reason": "something on the page is over the control",
                                   "facts": {"verdict": "covered", "error": "timeout"}}
    assert detailed["collected"] == 0
    assert sorted(app.paths.diagnostics.glob("survey-*.json"))
    said = " ".join(capsys.readouterr().out.split())
    assert "!! Something on the page covers the option for page 2" in said
    assert "Wrote diagnostic report" in said
