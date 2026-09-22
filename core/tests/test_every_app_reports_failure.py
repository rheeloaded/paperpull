"""Every app writes a failure file, and writes at most one.

The reason a new provider takes eight rounds is that the maintainer
cannot run it, and the tester sends back a sentence. This is the thing
that turns that sentence into evidence, so an app that quietly does not
do it is an app back on eight rounds without anybody noticing.
"""
import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def entries():
    out = []
    for app in sorted((REPO / "apps").iterdir()):
        if not app.is_dir():
            continue
        found = list(app.glob("*_docs.py")) + list(app.glob("*_receipts.py"))
        if found:
            out.append(found[0])
    return out


ENTRIES = entries()
IDS = [p.parent.name for p in ENTRIES]


def source(path):
    return io.open(path, encoding="utf-8", errors="ignore").read()


def test_there_are_apps_to_check():
    assert len(ENTRIES) > 40


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_app_can_write_a_failure_file(entry):
    text = source(entry)
    assert "from paperpull_core import failure" in text
    assert "def write_failure(self" in text


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_app_actually_calls_it_somewhere(entry):
    """A method nobody calls is eight rounds with extra steps."""
    calls = re.findall(r"\bself\.write_failure\(", source(entry))
    assert calls, "nothing in this app ever writes a failure file"


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_only_the_first_failure_of_a_run_writes_one(entry):
    """A run where thirty documents fail for one reason does not need
    thirty files, and the thirtieth is taken long after the page has
    moved on from the thing that broke."""
    text = source(entry)
    m = re.search(r"def write_failure\(self.*?(?=\n    def )", text, re.S)
    assert m, "no method to check"
    body = m.group(0)
    assert 'if self.stats.get("failure_files"):' in body
    assert "return" in body


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_it_hands_over_the_apps_own_selectors(entry):
    """The census is the whole point, and it needs the table."""
    text = source(entry)
    m = re.search(r"def write_failure\(self.*?(?=\n    def )", text, re.S)
    assert 'selectors=getattr(site, "FALLBACK", None)' in m.group(0)


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_it_names_its_provider(entry):
    text = source(entry)
    m = re.search(r"def write_failure\(self.*?(?=\n    def )", text, re.S)
    assert re.search(r"provider=['\"][^'\"]+['\"]", m.group(0)), \
        "a file that does not say which provider it came from"


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_writing_one_can_never_stop_a_run(entry):
    """It runs when something has already gone wrong. A diagnostic that
    raises in the middle of a failure costs the round it was meant to
    save, so nothing in the method may be left unguarded."""
    text = source(entry)
    m = re.search(r"def write_failure\(self.*?(?=\n    def )", text, re.S)
    body = m.group(0)
    # The one thing that could raise is reading the file back to say
    # what is in it, and it is wrapped.
    assert "try:" in body and "except Exception:" in body


def test_no_app_writes_a_failure_file_from_a_look_only_run():
    """Diagnose and record download nothing, so they have nothing to
    fail at, and a file from one of them would be noise."""
    for entry in ENTRIES:
        text = source(entry)
        for mode in ("cmd_diagnose", "cmd_record"):
            m = re.search(r"def %s\(self.*?(?=\n    def )" % mode, text, re.S)
            if m:
                assert "self.write_failure(" not in m.group(0), \
                    "%s calls it from %s" % (entry.parent.name, mode)
