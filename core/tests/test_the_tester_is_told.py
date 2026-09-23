"""A diagnostic nobody is told about is worth nothing.

Every app writes a failure file when a run stops early. That took a
release to build and the tester-facing docs went out without a word about
it, so for one release the only trace of it was three lines in a console.
These pin the telling to the thing itself.
"""
import io
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TESTER_PAGE = REPO / "docs" / "testing-a-provider.md"


def read(path):
    return io.open(path, encoding="utf-8", errors="ignore").read()


def asking_for_testers():
    """An app whose README asks somebody to test it."""
    out = []
    for app in sorted((REPO / "apps").iterdir()):
        readme = app / "README.md"
        if readme.is_file() and "Help test it" in read(readme):
            out.append(readme)
    return out


READMES = asking_for_testers()
IDS = [p.parent.name for p in READMES]


def test_some_providers_are_asking_for_testers():
    assert READMES, "no README asks for a tester, so this test proved nothing"


# -- the walkthrough ----------------------------------------------------------

def test_the_tester_page_says_a_failed_run_writes_one():
    page = read(TESTER_PAGE)
    assert "failure-" in page
    assert "Diagnostics" in page


def test_the_tester_page_says_to_attach_it():
    """Knowing the file exists and knowing to send it are two facts, and
    only the second one saves a round."""
    page = read(TESTER_PAGE)
    assert "Attach that file to the issue" in page


def test_the_tester_page_says_what_is_in_it_and_what_is_not():
    page = read(TESTER_PAGE).lower()
    assert "what is in it" in page
    assert "what is not in it" in page
    for promised in ("no account number", "no screenshot", "no password"):
        assert promised in page, promised


def test_the_tester_page_says_they_can_read_it_first():
    assert "Notepad" in read(TESTER_PAGE)


def test_the_section_is_in_the_contents():
    page = read(TESTER_PAGE)
    assert "#if-a-run-fails-send-the-file-it-wrote" in page
    assert "## If a run fails, send the file it wrote" in page


# -- and each provider's own page ---------------------------------------------

@pytest.mark.parametrize("readme", READMES, ids=IDS)
def test_a_provider_asking_for_a_tester_mentions_the_failure_file(readme):
    page = read(readme)
    assert "failure-" in page, (
        "%s asks for a tester without telling them a failed run writes a "
        "file worth attaching" % readme.parent.name)


@pytest.mark.parametrize("readme", READMES, ids=IDS)
def test_and_says_it_holds_nothing_from_their_account(readme):
    """A tester who is not told that will not attach it, and is right not
    to."""
    page = read(readme).lower()
    assert "no text from your account" in page


# -- the maintainer's half ----------------------------------------------------

def test_contributing_says_to_read_the_failure_file_first():
    page = read(REPO / "CONTRIBUTING.md")
    assert "failure-<command>-<timestamp>.json" in page
    assert "failure-diagnostics.md" in page


def test_the_design_note_it_points_at_exists():
    assert (REPO / "docs" / "failure-diagnostics.md").is_file()


# -- and the panel, which is where a tester actually is -----------------------

def test_the_panel_offers_the_file_rather_than_printing_a_path():
    page = read(REPO / "gui" / "app.py")
    assert "Show the file to attach" in page
    assert "/api/failure/latest" in page
