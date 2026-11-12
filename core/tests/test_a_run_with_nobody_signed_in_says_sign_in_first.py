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


def _is_attach(statement):
    """A statement that is the attach itself, `connect_over_cdp(cdp_url, ...)`
    alone or assigned, with any keyword settings after cdp_url."""
    value = statement.value if isinstance(statement, (ast.Assign, ast.Expr)) else None
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and value.func.attr == "connect_over_cdp" and bool(value.args)
            and isinstance(value.args[0], ast.Name) and value.args[0].id == "cdp_url")


def _raises_not_signed_in(statement, name):
    return (isinstance(statement, ast.Raise) and isinstance(statement.exc, ast.Call)
            and isinstance(statement.exc.func, ast.Name)
            and statement.exc.func.id == "not_signed_in"
            and not statement.exc.keywords
            and [getattr(arg, "id", None) for arg in statement.exc.args] == ["cdp_url", name])


def attach_reports_not_signed_in(src):
    """The attach is a statement of a try's own body, and that try's
    `except Exception as e` raises not_signed_in(cdp_url, e) as a statement
    of its own body. Both directly, never inside a nested block, since an
    inner try or a branch there can swallow the failure."""
    for block in ast.walk(ast.parse(src)):
        if not isinstance(block, ast.Try) or not any(_is_attach(s) for s in block.body):
            continue
        for handler in block.handlers:
            if (isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
                    and handler.name
                    and any(_raises_not_signed_in(s, handler.name) for s in handler.body)):
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


@pytest.mark.parametrize("source", [
    # An inner try around the attach swallows its failure.
    """
try:
    try:
        browser = chromium.connect_over_cdp(cdp_url)
    except Exception:
        browser = None
except Exception as error:
    raise not_signed_in(cdp_url, error)
""",
    # The raise sits in a branch the handler may never take.
    """
try:
    browser = chromium.connect_over_cdp(cdp_url)
except Exception as error:
    if quiet:
        raise not_signed_in(cdp_url, error)
""",
    # The handler raises with another exception than the one it caught.
    """
try:
    browser = chromium.connect_over_cdp(cdp_url)
except Exception as error:
    raise not_signed_in(cdp_url, other)
""",
], ids=["inner_try", "in_a_branch", "another_exception"])
def test_attach_check_refuses_a_failure_that_can_be_swallowed(source):
    assert not attach_reports_not_signed_in(source)



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
