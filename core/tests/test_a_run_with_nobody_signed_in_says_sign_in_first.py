"""A run that finds nobody signed in says to sign in first.

Get new pressed before Open sign-in window, the likeliest first-run slip,
read as a crash: "This run ended with a problem. It exited with code 1",
with the terminal's "Run login.bat first" in the details, "Sign in again"
to somebody who never had, and Continue for a run that never started.
Each app now ends that run through run_reporting.not_signed_in, which says
it in the words of where it runs and exits NOT_SIGNED_IN, and the panel
says "Sign in first" over it.
"""
import ast
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
    assert attach_reports_not_signed_in(src), "the failed attach ends through not_signed_in"


def attach_reports_not_signed_in(src):
    """Follow the attach's own exception handler, including optional CDP settings."""
    for block in ast.walk(ast.parse(src)):
        if not isinstance(block, ast.Try):
            continue
        attaches = [call for statement in block.body for call in ast.walk(statement)
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "connect_over_cdp" and call.args
                    and isinstance(call.args[0], ast.Name) and call.args[0].id == "cdp_url"]
        if not attaches:
            continue
        for handler in block.handlers:
            if not isinstance(handler.type, ast.Name) or handler.type.id != "Exception":
                continue
            for node in ast.walk(handler):
                if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                        and isinstance(node.exc.func, ast.Name)
                        and node.exc.func.id == "not_signed_in"
                        and len(node.exc.args) == 2
                        and all(isinstance(arg, ast.Name) for arg in node.exc.args)
                        and [arg.id for arg in node.exc.args] == ["cdp_url", handler.name]):
                    return True
    return False


def test_attach_check_follows_settings_and_the_same_exception_handler():
    source = """
try:
    browser = chromium.connect_over_cdp(cdp_url, no_defaults=True)
except Exception as error:
    cleanup()
    raise not_signed_in(cdp_url, error)
"""
    assert attach_reports_not_signed_in(source)
    assert not attach_reports_not_signed_in(source.replace("not_signed_in(cdp_url, error)", "error"))
    assert not attach_reports_not_signed_in(source.replace("connect_over_cdp", "unrelated"))



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


def test_its_result_line_offers_no_continue(capsys):
    """A real run ended "Sign in first" and then "Continue carries on"."""
    try:
        raise not_signed_in("http://127.0.0.1:9236", OSError("x"))
    except SystemExit:
        run_reporting.report_run_result({"new_files": []})
    assert "stopped before it finished" not in capsys.readouterr().out


def test_after_signing_in_names_the_button_under_the_panel(monkeypatch):
    monkeypatch.setenv(MARK_ENV, "0" * 32)
    assert run_reporting.after_sign_in() == "press Try the newest few first"
    monkeypatch.delenv(MARK_ENV)
    assert run_reporting.after_sign_in() == "run the pilot"
