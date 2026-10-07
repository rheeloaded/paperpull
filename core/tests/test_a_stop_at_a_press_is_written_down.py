"""A stop at a press ends the run the way it says it does, in every app that
presses through paperpull_core.pressing.

pressing.stop_run saves the run's progress, says why the run stopped and
has the app write its failure file with the stop's facts, through the app's
own write_failure(..., extra=facts). Twelve apps whose fallback press now
goes through pressing.press_once had a write_failure that took no extra, so
a stop there would have ended the run on a TypeError, with nothing said in
the run's own words and no failure file written. The census beside this one
reads only that main() catches the stop, and the browser tests call each
capture by itself, so neither could see it.

Each app's own main is run here with a made-up config and no browser, and
its run stops at a press the moment it starts. Every word here is made up.
"""
import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

from paperpull_core import pressing

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    found = sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py"))
    return found[0] if found else None


def presses_through_pressing(app: Path) -> bool:
    for path in sorted(app.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "pressing"
                    and node.attr in ("click", "check", "press_once")):
                return True
    return False


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and not d.name.startswith(("_", ".")) and entry_of(d)
              and presses_through_pressing(d))


def load(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith(("_docs", "_receipts", "_site")) or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module(entry_of(app).stem)
    finally:
        sys.path.pop(0)


def test_every_app_that_presses_through_pressing_is_here():
    """Not vacuous. American Express, Vanguard and the twelve whose fallback
    press goes through press_once, found by what their code calls."""
    assert {d.name for d in APPS} >= {
        "amex", "vanguard", "adp", "amfam", "applecard", "att", "etrade", "golden1",
        "newrez", "pge", "sba", "smud", "statefarm", "verizonmobile", "wellsfargo"}


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_stop_at_a_press_is_said_and_written_down(app, tmp_path, monkeypatch, capsys):
    mod = load(app)
    example = app / "config.example.json"
    config = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    config.update({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                   "profile_dir": str(tmp_path / "profile"), "cdp_url": "http://127.0.0.1:9",
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    import playwright.sync_api as sync_api

    def no_browser(*_args, **_kwargs):
        raise AssertionError("nothing here starts a browser")
    monkeypatch.setattr(sync_api, "sync_playwright", no_browser)
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: (_ for _ in ()).throw(EOFError()))

    def stops_at_a_press(self, *_args, **_kwargs):
        raise pressing.Covered(
            "press a control", "something on the page is over the control",
            ["Something on the page covers the control for this document, so nothing was "
             "pressed.", pressing.AGAIN],
            {"verdict": "covered", "error": "timeout"}, after_a_press=True)
    monkeypatch.setattr(mod.App, "cmd_run", stops_at_a_press)
    capsys.readouterr()
    with pytest.raises(SystemExit) as ended:
        mod.main(["--config", str(cfg), "--all", "--yes"])
    said = " ".join(capsys.readouterr().out.split())
    assert ended.value.code == 0, said[-1500:]
    assert "!! Something on the page covers the control for this document" in said, said[-1500:]
    written = sorted((tmp_path / "out").rglob("failure-*.json"))
    assert len(written) == 1, sorted(p.name for p in (tmp_path / "out").rglob("*"))
    report = json.loads(written[0].read_text(encoding="utf-8"))
    assert report["step"] == "press a control"
    assert report["reason"] == "something on the page is over the control"
    assert report["extra"]["verdict"] == "covered"
