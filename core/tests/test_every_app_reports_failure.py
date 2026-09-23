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


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_app_keeps_a_journal(entry):
    """The census says what the page looked like when a run gave up. The
    journal is the only thing that can speak for a layer it got past."""
    text = source(entry)
    assert "from paperpull_core.journal import Journal" in text
    assert "def journal(self)" in text


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_journal_is_made_only_when_something_writes_to_it(entry):
    """A run that never opens a page has nothing to say, and must not
    fail differently because of this."""
    m = re.search(r"def journal\(self\).*?(?=\n    def )", source(entry), re.S)
    assert m, "no property to check"
    assert "if self._journal is None:" in m.group(0)


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_failure_file_carries_the_journal(entry):
    m = re.search(r"def write_failure\(self.*?(?=\n    def )",
                  source(entry), re.S)
    assert "journal=self._journal" in m.group(0), \
        "a failure file with nothing about how the run got there"


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_app_marks_a_document_it_saved(entry):
    """The entry a later failure is read against. Without one, a run
    that saved three documents and then broke looks the same as a run
    that never saved anything."""
    assert re.search(r"self\.journal\.checkpoint\(", source(entry)), \
        "nothing in this app records a document going well"


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_app_counts_the_calls_the_provider_answered(entry):
    """Eleven of these drive an API and declare no selectors, so the
    selector census has nothing to say about them. This is their half,
    and it is on every app because a page-driven one calls an API too."""
    text = source(entry)
    assert "from paperpull_core.api_census import Requests" in text
    assert "def requests(self)" in text


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_it_starts_listening_where_the_page_is_made(entry):
    """It only sees what arrives after it starts, so starting it at the
    first failure would be starting it too late."""
    text = source(entry)
    m = re.search(r"\n    def page\(self.*?(?=\n    def )", text, re.S)
    assert m, "no page method"
    assert "self.requests" in m.group(0), \
        "nothing starts the request census when the page is made"


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_the_failure_file_carries_the_calls(entry):
    m = re.search(r"def write_failure\(self.*?(?=\n    def )",
                  source(entry), re.S)
    assert "requests=self._requests" in m.group(0)
