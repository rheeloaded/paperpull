"""Diagnose writes a file that is safe to attach, and says which one.

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

So Diagnose writes that survey too, and that is the file it names. The
detailed one stays where it is, because it is what a repair is read from,
and it is now described as staying on this machine.
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
def test_the_detailed_file_says_it_stays_here(app):
    src = entry_of(app).read_text(encoding="utf-8")
    assert "stays on this machine" in src, \
        "%s writes the detailed file without saying what it is" % app.name


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
    note = json.loads(Path(path).read_text(encoding="utf-8"))["note"]
    assert "attach" in note.lower()
    assert "stay on this machine" in note.lower()


def test_what_diagnose_prints_names_the_safe_file(tmp_path):
    said = []
    failure.write_survey(tmp_path, provider="Testco", say=said.append)
    joined = " ".join(said).lower()
    assert "safe to send" in joined
    assert "attach it" in joined
    assert "stays on this machine" in joined


# -- and the panel points at the right one -------------------------------------

def test_the_panel_no_longer_tells_people_to_attach_the_detailed_file():
    page = (REPO / "gui" / "app.py").read_text(encoding="utf-8")
    start = page.index("<b>Diagnose</b>")
    blurb = page[start:start + 700]
    assert "survey-" in blurb, "the panel does not say which file to attach"
    assert "stay on this machine" in blurb or "stays on this machine" in blurb
