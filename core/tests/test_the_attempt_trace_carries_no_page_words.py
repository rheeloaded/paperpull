"""The third file testers are told to attach.

When a capture fails, twelve apps write download-attempt.json and print
"attach it to the issue". It is a trace of what the site answered, and the
URL in it goes through redaction. The label of the control that was clicked
did not, in fifty-five places across eleven apps, and a control on a bank
page is called things like "Pay SAPPHIRE RESERVE (...1234)".

ADP's trace also carried three hundred characters of ADP's own refusal
message, which on a step-up says where the code was sent.

These files really are attached. Thirteen detailed Diagnose files and six
download-attempt.json files are on public issues in this repository right
now, from two testers, covering a credit union, a brokerage, a mortgage
servicer and a payroll system.

Redaction is the weaker of the two answers here and the file is built by
collecting rather than by allowlisting, so this checks the narrow thing it
can check: nothing goes into the trace that has not been through it.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Fields whose value came off the page and must be cleaned on the way in.
FROM_THE_PAGE = {"control", "label", "text", "message", "url", "href",
                 "title", "name", "identity"}
CLEANERS = ("redact", "mask_text", "mask_href", "mask", "_redact")

APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists())


def trace_entries(tree):
    """Every dictionary handed to a trace."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"):
            continue
        if "trace" not in ast.unparse(node.func.value):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                yield node.lineno, arg


def is_cleaned(value) -> bool:
    text = ast.unparse(value)
    if any(c + "(" in text for c in CLEANERS):
        return True
    # a literal the app wrote itself, or a plain number or flag
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.JoinedStr):
        return all(is_cleaned(v.value) for v in value.values
                   if isinstance(v, ast.FormattedValue))
    return False


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_nothing_reaches_the_trace_without_being_cleaned(app):
    path = app / ("%s_site.py" % app.name)
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    raw = []
    for line, entry in trace_entries(tree):
        for key, value in zip(entry.keys, entry.values):
            if not (isinstance(key, ast.Constant) and key.value in FROM_THE_PAGE):
                continue
            if is_cleaned(value):
                continue
            raw.append("line %d, %s = %s" % (line, key.value, ast.unparse(value)[:50]))
    assert not raw, (
        "%s puts the page's own words in a file it tells people to attach: %s"
        % (app.name, "; ".join(raw)))


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_the_file_it_writes_says_where_it_landed_without_saying_the_address(app):
    for entry in sorted(app.glob("*_docs.py")) + sorted(app.glob("*_receipts.py")):
        src = entry.read_text(encoding="utf-8", errors="ignore")
        if "download-attempt.json" not in src:
            continue
        line = next(ln for ln in src.splitlines() if "landed_on" in ln)
        assert any(c + "(" in line for c in CLEANERS), \
            "%s writes the address it landed on as it stands: %s" % (app.name, line.strip())


def test_the_cleaner_does_what_this_is_trusting_it_to_do():
    """Redaction is the weaker answer and it still has to work."""
    from paperpull_core.redact import redact, set_private_words
    set_private_words(["Dana Quill"])
    try:
        for secret, gone in (
                ("Pay SAPPHIRE RESERVE (...1234)", "1234"),
                ("Welcome back, Dana Quill", "Dana"),
                ("Balance $12,345.67", "12,345.67"),
                ("Account 4111111111111111", "4111111111111111"),
                ("https://bank.example/doc?token=abc123def456", "token=abc123def456")):
            assert gone not in redact(secret), secret
    finally:
        set_private_words([])
