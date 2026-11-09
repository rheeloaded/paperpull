"""A run that finds nobody signed in says to sign in first.

Get new pressed before Open sign-in window, the likeliest first-run slip,
read as a crash: "This run ended with a problem. It exited with code 1",
with the terminal's "Run login.bat first" in the details, "Sign in again"
to somebody who never had, and Continue for a run that never started.
Each app now ends that run through run_reporting.not_signed_in, which says
it in the words of where it runs and exits NOT_SIGNED_IN, and the panel
says "Sign in first" over it.
"""
import re
from pathlib import Path

import pytest

from paperpull_core import run_reporting
from paperpull_core.run_reporting import MARK_ENV, NOT_SIGNED_IN, not_signed_in

REPO = Path(__file__).resolve().parents[2]
ENTRIES = sorted(p for p in (REPO / "apps").glob("*/*.py") if p.name.endswith(("_docs.py", "_receipts.py")))


def test_there_are_apps_to_check():
    assert len(ENTRIES) >= 80


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.parent.name)
def test_every_app_ends_a_run_with_nobody_signed_in_the_same_way(entry):
    src = entry.read_text(encoding="utf-8")
    assert "Could not connect to your signed-in browser" not in src, "said in the core, not in the app"
    assert re.search(r"connect_over_cdp\(cdp_url\)\n\s*except Exception as e:\n(?:.*\n){0,3}?\s*raise not_signed_in\(cdp_url, e\)\n",
                     src), "the failed attach ends through not_signed_in"


def test_under_the_panel_it_names_the_panels_button(monkeypatch, capsys):
    monkeypatch.setenv(MARK_ENV, "0" * 32)
    exit_ = not_signed_in("http://127.0.0.1:9236", ConnectionRefusedError("refused"))
    assert isinstance(exit_, SystemExit) and exit_.code == NOT_SIGNED_IN
    out = capsys.readouterr()
    assert out.out == ""
    assert "Press Open sign-in window" in out.err and "nothing was downloaded" in out.err
    assert "login.bat" not in out.err and "(refused)" in out.err


def test_in_a_terminal_it_names_login_bat(monkeypatch, capsys):
    monkeypatch.delenv(MARK_ENV, raising=False)
    assert not_signed_in("http://127.0.0.1:9236", OSError("x")).code == NOT_SIGNED_IN
    err = capsys.readouterr().err
    assert "Could not connect to your signed-in browser at http://127.0.0.1:9236." in err
    assert "Run login.bat first" in err and "Open sign-in window" not in err


def test_it_is_no_stop_with_a_reason():
    """Nothing started, so it is never said as a run that stopped partway."""
    try:
        raise not_signed_in("http://127.0.0.1:9236", OSError("x"))
    except SystemExit:
        assert run_reporting.stop_reason() == ""


def test_the_panels_server_keeps_the_same_number():
    src = (REPO / "gui" / "app.py").read_text(encoding="utf-8")
    m = re.search(r"^NOT_SIGNED_IN = (\d+)$", src, re.M)
    assert m and int(m.group(1)) == NOT_SIGNED_IN
