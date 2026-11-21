"""Login that meets the portal's bot check says Login could not read Bill
History, not that a run stops. All values are invented."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marinwater_docs as app_mod
import marinwater_site as site


def test_login_on_a_bot_check_speaks_of_login_not_a_run(monkeypatch, tmp_path, capsys):
    site._RUN.clear()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"owner": "Synthetic Owner", "output_dir": str(tmp_path)}),
                      encoding="utf-8")
    args = app_mod.build_parser().parse_args(["--config", str(config), "--login"])
    monkeypatch.setattr(app_mod.App, "_setup_logging", lambda self: None)
    app = app_mod.App(args)
    closed = []
    monkeypatch.setattr(app, "page", lambda: None)
    monkeypatch.setattr(app, "close", lambda: closed.append(1))

    def challenged(_page):
        raise site.Challenged("invented bot check")

    monkeypatch.setattr(site, "bill_list_opens", challenged)
    app.cmd_login()
    out = capsys.readouterr().out
    assert "this run stops here" not in out
    assert "Login could" in out and "not read Bill History" in out
    assert "re-run --login" in out
    assert closed == [1]
