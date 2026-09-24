"""No app waits at a prompt nobody can answer.

The panel runs an app with its stdin set to DEVNULL, deliberately, so a
stray prompt cannot hang a run. An app that calls input() there reads
end-of-file, and `ask` turns that into "No interactive console available,
run this from a real console window (use the .bat files)" and exits 3.

Which means everything after the prompt never happens. Press Login in the
panel and the sign-in is never confirmed, the run is reported as failed,
and the advice is to go and use a .bat file the person did not want. On
Target, which opens its own browser as a child process, the exit also
closed the window they were about to sign in to. That is issue #48, twice.

Target was fixed in 0.33.0 with pause_for_sign_in and ask_or_none, both of
which answer None rather than raising when there is nobody to ask. The
eight receipt apps had the same three prompts and nobody had asked them.

The prompts that remain are the ones where stopping is right. The --all
confirmation is one, and the panel passes --yes so it never arrives. The
rename editor is another, and it is a conversation by nature.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))

# Where a prompt means the run stops before it has done its job. These run
# from the panel's buttons.
UNATTENDED = ("cmd_login", "cmd_open_browser", "check_session", "cmd_discover",
              "cmd_run", "cmd_resume", "cmd_verify", "cmd_diagnose",
              "download_one", "process_one", "_record", "cmd_pilot")

# Prompts that are allowed to stop, because stopping is the right answer.
MAY_ASK = ("cmd_rename", "cmd_record", "_confirm", "_edit_summaries")


def prompts_in(fn) -> list:
    """Calls to the raising prompt, which is `ask`, not `ask_or_none`.

    A prompt the panel never reaches is fine. The --all confirmation sits
    behind `if not self.args.yes`, and the panel passes --yes with every
    run, so that one is asked only of somebody who is there to answer.
    """
    behind_yes = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "yes" in ast.unparse(node.test):
            for inner in ast.walk(node):
                behind_yes.add(id(inner))
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or id(node) in behind_yes:
            continue
        name = (node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", ""))
        if name == "ask":
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_nothing_the_panel_runs_waits_at_a_prompt(app):
    path = entry_of(app)
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in MAY_ASK or node.name not in UNATTENDED:
            continue
        for line in prompts_in(node):
            bad.append("%s() at line %d" % (node.name, line))
    assert not bad, (
        "%s waits for an answer the panel cannot give, so the run stops "
        "there and reports a failure: %s" % (app.name, ", ".join(bad)))


def waits_for_a_sign_in(app: Path) -> bool:
    """An app that HOLDS while somebody signs in, rather than opening a
    window and returning.

    Most do the latter. They open the browser, say to keep it open, and
    stop, which needs no prompt and is already right under the panel. Only
    the nine that hold are in question here.

    Found by what the command does. Keying on the words "finished signing
    in" worked until the fix replaced them, at which point every app
    skipped and this asserted nothing.
    """
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in ("cmd_open_browser", "cmd_login"):
            continue
        body = ast.unparse(node)
        if "pause_for_sign_in" in body or re.search(r"ask\(", body):
            return True
    return False


PAUSERS = [d for d in APPS if waits_for_a_sign_in(d)]


@pytest.mark.parametrize("app", PAUSERS, ids=lambda d: d.name)
def test_the_sign_in_pause_leaves_the_browser_open(app):
    """Not waiting must not be the same as failing. The person is looking
    at the window and about to use it."""
    src = entry_of(app).read_text(encoding="utf-8", errors="ignore")
    assert "pause_for_sign_in" in src, (
        "%s holds for a sign-in with a prompt that raises rather than with "
        "the helper that returns" % app.name)


def test_there_are_apps_that_hold_for_a_sign_in():
    """The check above is only worth having if it collects anybody, and it
    collected nobody once already."""
    assert len(PAUSERS) >= 9, (
        "no app was recognized as holding for a sign-in, so the check above "
        "passed by collecting nothing: %s" % [d.name for d in PAUSERS])


def test_the_helpers_answer_rather_than_raise_when_nobody_is_there(monkeypatch):
    """Everything above rests on these two, so they are exercised."""
    from paperpull_core import browser

    def no_console(*_a, **_k):
        raise EOFError("no stdin")

    monkeypatch.setattr(browser, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", no_console)
    assert browser.ask_or_none("anything? ") is None

    said = []
    assert browser.pause_for_sign_in(say=said.append) is False
    joined = " ".join(said).lower()
    assert "leave it open" in joined
    assert "panel" in joined


def test_the_helpers_still_wait_when_somebody_is_there(monkeypatch):
    from paperpull_core import browser
    monkeypatch.setattr(browser, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_a: "")
    assert browser.ask_or_none("anything? ") == ""
    assert browser.pause_for_sign_in(say=lambda *_a: None) is True
