"""A Citi support report that read the statement list is a report saved.

Citi's Diagnose counted the list its runs read as "rows_collected", which
the core did not read for whether a report read anything. So a report made
on the statements page, where the security check reader also found
something, ended as one that read nothing, and the person was told to sign
in. It counts the list as "collected" now. Citi's list reader refuses a page
its sign-in check calls signed out, so here the check that trips is the
security check one. Diagnose runs whole against the made-up signed-in page
of test_diagnose_names_no_card.py. No real account, no network.
"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import citi_docs as docs  # noqa: E402
import citi_site as site  # noqa: E402
from paperpull_core import run_reporting, words  # noqa: E402

from test_diagnose_names_no_card import _SignedInPage  # noqa: E402


def _app(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner": "Dana Example", "output_dir": str(tmp_path / "out"),
                               "profile_dir": str(tmp_path / "profile")}), encoding="utf-8")
    with mock.patch.object(docs.App, "_setup_logging", lambda self: None):
        app = docs.App(docs.build_parser().parse_args(["--config", str(cfg)]))
    page = _SignedInPage()
    app.page = lambda: page
    return app


def _info(app):
    return json.loads((app.paths.diagnostics / "diagnose-documents.json").read_text(encoding="utf-8"))


def test_a_list_read_where_a_check_tripped_is_a_report_saved(tmp_path, capsys):
    app = _app(tmp_path)
    with mock.patch.object(site, "detect_security_challenge", lambda _p: "A passcode prompt"):
        app.cmd_diagnose()
    assert not words.read_nothing_in(app.paths.diagnostics), "a list read is not nothing read"
    info = _info(app)
    assert info["challenge"] and info["collected"] > 0, info
    assert "rows_collected" not in info
    said = capsys.readouterr().out
    assert "rows: %d" % info["collected"] in said, said


def test_a_sign_in_page_reads_nothing_and_says_so(tmp_path):
    """Its list reader refuses a page with a password field, so the count is
    none and the report says to sign in."""
    app = _app(tmp_path)
    with mock.patch.object(site, "looks_signed_out", lambda _p: True):
        app.cmd_diagnose()
    info = _info(app)
    assert info["signed_out"] is True and info["collected"] == 0, info
    with pytest.raises(SystemExit) as out:
        app.write_survey()
    assert out.value.code == run_reporting.NOTHING_READ
