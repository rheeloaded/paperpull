"""PaperPull Server's pages say what the server does, and keep saying it.

SERVER.md, PRIVACY-SERVER.md and SECURITY-SERVER.md make promises about the
image, and a page that drifts from the code is worse than none. These tests
tie the promises that can be checked to the files that keep them.
"""
import ast
import json
import re
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
PAGES = ("SERVER.md", "PRIVACY-SERVER.md", "SECURITY-SERVER.md")


def prose(text: str) -> str:
    """A page without its code, fenced or inline."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


@pytest.mark.parametrize("page", PAGES)
def test_the_pages_keep_the_house_punctuation(page):
    text = (REPO / page).read_text(encoding="utf-8")
    assert "—" not in text, "an em dash"
    lines = [line for line in prose(text).splitlines() if ";" in line]
    assert not lines, lines


@pytest.mark.parametrize("page", PAGES)
def test_every_command_they_name_is_in_the_image(page):
    text = (REPO / page).read_text(encoding="utf-8")
    dockerfile = (SERVER / "Dockerfile").read_text(encoding="utf-8")
    for name in re.findall(r"/opt/paperpull/server/([\w.]+\.py)", text):
        assert (SERVER / name).is_file(), name
        assert "server/%s" % name in dockerfile, "%s is not copied into the image" % name


def test_the_files_the_setup_names_are_there():
    text = (REPO / "SERVER.md").read_text(encoding="utf-8")
    for rel in re.findall(r"`(server/[\w./-]+)`", text):
        assert (REPO / rel).exists(), rel


def test_a_rented_server_is_warned_about():
    """Bryan's call, a disclaimer and not a block, for the bot checks a
    data center's addresses draw."""
    text = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    assert "Not on a rented server" in text and "data-center addresses" in text
    assert "Robot or human?" in text


def test_what_the_privacy_page_says_is_off_is_off():
    policies = json.loads((SERVER / "chrome-policies.json").read_text(encoding="utf-8"))
    text = " ".join((REPO / "PRIVACY-SERVER.md").read_text(encoding="utf-8").split())
    assert ("Usage statistics, sync, signing in to the browser, search suggestions, "
            "spell checking and translation are switched off by policy") in text
    assert policies["MetricsReportingEnabled"] is False
    assert policies["SyncDisabled"] is True
    assert policies["BrowserSignin"] == 0
    assert policies["SearchSuggestEnabled"] is False
    assert policies["SpellCheckServiceEnabled"] is False
    assert policies["TranslateEnabled"] is False


def panel_setting(name: str):
    """A number set at the top of gui/server_mode.py. Read rather than
    imported, because the Python that runs this suite may not have FastAPI,
    and a check that skips itself there would never be seen to fail."""
    tree = ast.parse((REPO / "gui" / "server_mode.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), "server_mode.py", "eval"), {"__builtins__": {}})
    raise AssertionError("%s is not set in gui/server_mode.py" % name)


def test_what_the_security_page_says_about_waiting_matches_the_panel():
    text = " ".join((REPO / "SECURITY-SERVER.md").read_text(encoding="utf-8").split())
    assert "After five wrong passwords" in text and panel_setting("FREE_TRIES") == 5
    assert "up to a quarter of an hour" in text and panel_setting("LONGEST_WAIT") == 15 * 60
    assert "A session lasts 14 days" in text and panel_setting("SESSION_SECONDS") == 14 * 86400


def test_the_names_the_setup_says_the_panel_answers_to_are_the_panels():
    """A name the page promises and the panel refuses locks a person out of
    their own server, and one the panel takes that the page leaves out is a
    name nobody checked."""
    text = " ".join((REPO / "SERVER.md").read_text(encoding="utf-8").split())
    said = text[text.index("The panel answers to the server's address"):]
    said = said[:said.index("separated by commas")]
    assert set(re.findall(r"`(\.[a-z.]+)`", said)) == set(panel_setting("LOCAL_SUFFIXES"))
    assert "one without a dot such as `nas`" in said and "`PAPERPULL_HOSTS`" in said
    compose = (SERVER / "compose.yaml").read_text(encoding="utf-8")
    assert '# PAPERPULL_HOSTS: "' in compose


@pytest.mark.parametrize("page, server_page", [
    ("PRIVACY.md", "PRIVACY-SERVER.md"),
    ("SECURITY.md", "SECURITY-SERVER.md"),
    ("README.md", "SERVER.md"),
])
def test_the_desktop_pages_point_to_the_servers(page, server_page):
    assert "(%s)" % server_page in (REPO / page).read_text(encoding="utf-8")
