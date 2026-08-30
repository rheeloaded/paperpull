"""Every app's document_rules.json must contain real regexes, not corruption.

A regex like "\\b1099\\b" has repeatedly been written into these files with one
backslash level eaten, leaving a literal BACKSPACE (0x08) where the word
boundary should be. The pattern then silently matches nothing and documents get
misfiled under the wrong name.

Checking the file's BYTES is not enough and gave false assurance twice: JSON
escapes a backspace as the two characters \\b, so a corrupted file looks clean
on disk while the PARSED value holds a control character. These tests read the
parsed values, and also confirm each pattern actually compiles and that a
word-boundary pattern really contains one.
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RULES_FILES = sorted(REPO.glob("apps/*/document_rules.json"))
RULE_LISTS = ("tax_rules", "year_end_rules", "insurance_rules", "statement_rules")

CONTROL = set(range(0, 9)) | set(range(14, 32))


def _patterns(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in RULE_LISTS:
        for rule in data.get(key, []):
            yield key, rule.get("pattern", ""), rule.get("summary", "")
    for pat in data.get("skip_patterns", []):
        yield "skip_patterns", pat, ""


def test_there_are_rules_files_to_check():
    assert RULES_FILES, "expected at least one apps/*/document_rules.json"


@pytest.mark.parametrize("path", RULES_FILES, ids=lambda p: p.parent.name)
def test_no_control_characters_in_any_parsed_value(path):
    """The check that matters: the VALUE, after JSON parsing."""
    for key, pattern, summary in _patterns(path):
        for field, value in (("pattern", pattern), ("summary", summary)):
            bad = [c for c in value if ord(c) in CONTROL]
            assert not bad, (
                f"{path.parent.name}/{key} {field}={value!r} contains control "
                f"character(s) {[hex(ord(c)) for c in bad]} - a backslash "
                f"escape was eaten when this file was written")


@pytest.mark.parametrize("path", RULES_FILES, ids=lambda p: p.parent.name)
def test_every_pattern_compiles(path):
    for key, pattern, _ in _patterns(path):
        try:
            re.compile(pattern, re.I)
        except re.error as e:
            raise AssertionError(
                f"{path.parent.name}/{key}: {pattern!r} does not compile ({e})")


@pytest.mark.parametrize("path", RULES_FILES, ids=lambda p: p.parent.name)
def test_a_pattern_that_looks_like_it_wants_a_word_boundary_has_one(path):
    r"""If the JSON text shows \b, the parsed value must be a two-character
    backslash-b, never the single backspace character."""
    raw = path.read_text(encoding="utf-8")
    if "\\\\b" not in raw and "\\b" not in raw:
        return
    for key, pattern, _ in _patterns(path):
        assert "\x08" not in pattern, (
            f"{path.parent.name}/{key}: {pattern!r} holds a backspace where a "
            f"word boundary was intended")
