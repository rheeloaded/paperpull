"""Every file Diagnose writes for a tester is built from what may leave.

The panel said, of Diagnose, "Attach that file to an issue". The file it
meant carries the page's own title, the URL with its query string, the text
of every row it found and the label of every control, and in twenty-four of
the apps a full page screenshot of a signed-in bank, insurer, payroll system
or government pay portal sits beside it. Two hundred and seventy-four reads
straight off the page, across the apps, and twenty-four of them put not one
of those through redaction.

Redaction would not have been the answer anyway. That was settled when the
failure file was built: a canary page carrying a distinctive fake secret in
every channel a browser offers gave up eleven of twenty-one through
redaction, which is why that file is built from a list of what may leave
instead.

So Diagnose wrote that survey too, and named it, and the detailed file was
to stay on the tester's machine. Eighteen apps still told the tester to
attach it, with whatever its samples held, an address or a vehicle among
them, and thirteen told the tester to attach the file a failed download
writes. So every file an app writes for a tester now goes through
the word list in paperpull_core.words on its way to the disk, where a word
off the list leaves as its shape. A screenshot cannot be built from a list,
and it is the one thing said to stay.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO / "core"))
from paperpull_core import failure  # noqa: E402


def entry_of(app: Path):
    for pattern in ("*_docs.py", "*_receipts.py"):
        found = sorted(app.glob(pattern))
        if found:
            return found[0]
    return None


APPS = sorted(d for d in (REPO / "apps").iterdir() if d.is_dir() and entry_of(d))

# The files an app writes for a tester to read and attach.
TESTER_FILES = ("diagnose-", "download-attempt.json", "discovery-trace.json")


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ast.unparse(n.func) == name]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_this_app_writes_the_safe_survey_when_diagnose_runs(app):
    src = entry_of(app).read_text(encoding="utf-8")
    assert "def write_survey" in src, \
        "%s has no survey to offer, so the only file it writes is the raw one" % app.name
    assert "failure.write_survey(" in src, \
        "%s builds its own instead of using the one list of what may leave" % app.name


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_running_diagnose_is_what_triggers_it(app):
    """Next to cmd_diagnose in the source is not the same as being called."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    ran = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = ast.unparse(node.test)
        if "args.diagnose" not in test:
            continue
        body = " ".join(ast.unparse(n) for n in node.body)
        ran.append(("cmd_diagnose" in body, "write_survey" in body))
    assert ran, "%s never runs cmd_diagnose from --diagnose" % app.name
    assert any(both for both in (a and b for a, b in ran)), (
        "%s runs Diagnose without writing the survey beside it" % app.name)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_file_written_for_a_tester_goes_through_the_word_list(app):
    """Found by what a function does, naming one of those files, rather
    than by its name, so a command added later is held to it too. JSON
    written any other way is a page's words copied as they were."""
    for path in [entry_of(app)] + sorted(app.glob("*_site.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            named = [c.value for c in ast.walk(fn) if isinstance(c, ast.Constant)
                     and isinstance(c.value, str) and c.value.startswith(TESTER_FILES)]
            if not named:
                continue
            by_hand = [ast.unparse(c)[:80] for c in _calls(fn, "atomic_write_text")
                       if len(c.args) > 1 and isinstance(c.args[1], ast.Call)
                       and ast.unparse(c.args[1].func) in
                       ("json.dumps", "_json.dumps", "site.to_json")]
            assert not by_hand, "%s %s writes %s by hand: %s" % (
                app.name, fn.name, named, by_hand)
            if any(n.endswith(".json") for n in named):
                assert _calls(fn, "write_shaped"), "%s %s names %s and never writes it " \
                    "through write_shaped" % (app.name, fn.name, named)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_every_shaped_write_names_the_app_by_its_source(app):
    """The app's own words come from what its source calls it, the name it
    gives the survey and its site module, and from nothing a page said."""
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    provider = next(ast.unparse(k.value) for n in _calls(tree, "failure.write_survey")
                    for k in n.keywords if k.arg == "provider")
    for call in _calls(tree, "write_shaped"):
        assert len(call.args) == 3, ast.unparse(call)[:80]
        assert ast.unparse(call.args[2]) == "words_for(%s, site)" % provider, \
            ast.unparse(call)[:100]


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_the_detailed_file_says_how_it_is_built(app):
    tree = ast.parse(entry_of(app).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "cmd_diagnose":
            said = ast.unparse(fn)
            assert "not on PaperPull's fixed list" in said, \
                "%s writes the detailed file without saying what it is" % app.name
            if "screenshot(" in said:
                assert "stays" in said and "on this machine" in said, \
                    "%s takes a screenshot without saying it stays here" % app.name
            return
    pytest.fail("%s has no cmd_diagnose" % app.name)


# -- what the survey itself may carry ------------------------------------------

def test_the_survey_is_the_same_kind_of_file_as_a_failure_report(tmp_path):
    path = failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    assert path, "the survey could not be written"
    import json
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    assert report["kind"] == "paperpull-survey"
    assert report["command"] == "diagnose"
    assert Path(path).name.startswith("survey-diagnose-")


def test_the_survey_refuses_anything_that_is_not_on_the_list(tmp_path):
    """Handed a page's own words through the one door that takes a
    dictionary, they must not come out the other side."""
    import json
    secret = "Dana Quill, 4111111111111111, 12 Example Street"
    path = failure.write_survey(
        tmp_path, provider="Testco", say=lambda *_a: None,
        extra={"page_title": secret, "url": "https://bank.example/a?token=" + secret,
               "rows": [secret, secret], "count": 7, "found": True})
    text = Path(path).read_text(encoding="utf-8")
    for leak in ("Dana", "Quill", "4111", "Example Street", "token"):
        assert leak not in text, "the survey carried %r out" % leak
    report = json.loads(text)
    assert report["extra"]["count"] == 7
    assert report["extra"]["found"] is True


def test_the_survey_tells_the_reader_which_file_this_is(tmp_path):
    import json
    path = failure.write_survey(tmp_path, provider="Testco", say=lambda *_a: None)
    note = json.loads(Path(path).read_text(encoding="utf-8"))["note"].lower()
    assert "attach" in note
    assert "fixed list" in note, "it does not say how the detailed file is built"
    assert "screenshot" in note and "stays on this machine" in note


def test_what_diagnose_prints_names_the_safe_file(tmp_path):
    said = []
    failure.write_survey(tmp_path, provider="Testco", say=said.append)
    joined = " ".join(said).lower()
    assert "safe to send" in joined
    assert "attach it" in joined
    assert "detailed file beside it can go with it" in joined
    assert "stays on this machine" in joined


# -- and the panel says the same -------------------------------------------------

def test_the_panel_says_how_each_file_diagnose_writes_is_built():
    page = (REPO / "gui" / "app.py").read_text(encoding="utf-8")
    start = page.index("<b>Diagnose</b>")
    blurb = " ".join(page[start:start + 900].split())
    assert "survey-" in blurb, "the panel does not say which file to attach"
    assert "fixed list" in blurb, "the panel does not say how the detailed file is built"
    assert "screenshot" in blurb and "stays on this machine" in blurb
