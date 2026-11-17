"""A failure file can carry page facts read earlier in the run (threads of
2026-11-16, item 5).

Anthem's Run All reads the page where its EOB list would not open, goes on
to its other lists, and writes the EOB stop's file at its end. The file
takes the page and selectors read at the refusal through
failure.write_failure's page_facts, in place of a read of the tab at the
stop. They leave through the same word list as a live read. Every other
caller passes nothing and gets the file it always did. Every value is
invented, and a canary must never come out.
"""
import ast
import json
from pathlib import Path

import pytest

from paperpull_core import failure

REPO = Path(__file__).resolve().parents[2]
CANARY = "CANARY-7Q3 Dana Example 4111 Elm Lane"


class Page:
    """A page whose every read is counted, and whose answers carry a canary."""

    def __init__(self, length=4444):
        self.reads = 0
        self.length = length
        self.url = "https://member.example.invalid/?who=" + CANARY.replace(" ", "+")

    def evaluate(self, script, *args):
        self.reads += 1
        node = {"tag": "div", "cls": "canary-7q3-member", "text": CANARY, "w": 10, "h": 10}
        if script == failure._PAGE_STATE_JS:
            return {"ready": "complete", "body_text_len": self.length, "largest_visible": node,
                    "Custom Cash": CANARY}
        if script == failure._CENSUS_JS:
            return [{"matched": self.length // 1111, "visible": 1, "nodes": [node]}
                    for _ in args[0]]
        return 0


def write(tmp_path, **kw):
    path = failure.write_failure(tmp_path, command="all", step="open the eob list",
                                 reason="the eob list would not open", provider="Anthem",
                                 say=lambda *_a: None, **kw)
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text), text


def test_facts_read_earlier_are_written_in_place_of_a_read_now(tmp_path):
    earlier = Page(1111)
    facts = failure.page_facts(earlier, {"eob_row": "tr.eob"})
    page = Page()
    report, text = write(tmp_path, page=page, selectors={"eob_row": "tr.eob"}, page_facts=facts)
    assert page.reads == 0
    assert report["page"]["body_text_len"] == 1111
    assert report["selectors"][0]["matched"] == 1
    # Y3.1. Through the same reads and the same word list as a read now.
    now, _ = write(tmp_path / "now", page=Page(1111), selectors={"eob_row": "tr.eob"})
    assert (report["page"], report["selectors"]) == (now["page"], now["selectors"])
    assert "CANARY" not in text and "Elm Lane" not in text and "canary-7q3-member" not in text


def test_no_facts_reads_the_page_as_before(tmp_path):
    page = Page()
    report, _text = write(tmp_path, page=page, page_facts=None)
    assert page.reads >= 1 and report["page"]["body_text_len"] == 4444


@pytest.mark.parametrize("facts", [
    ["a", CANARY], CANARY, 7,
    {"page": {"largest_visible": {"text": CANARY, "cls": "canary-7q3-member"},
              "Custom Cash": CANARY, "body_text_len": 1111},
     "selectors": [{"name": CANARY, "matched": 1}]}],
    ids=["list", "text", "number", "a dict made some other way"])
def test_facts_not_read_by_page_facts_are_refused(tmp_path, facts):
    """Y2.5. Never written, and the page is not read in their place. A dict
    made by hand never went through the reads that keep a page's text out."""
    page = Page()
    report, text = write(tmp_path, page=page, page_facts=facts)
    assert "page" not in report and "selectors" not in report
    assert page.reads == 0 and "CANARY" not in text


def test_only_anthem_hands_page_facts_to_a_failure_file():
    """Y1.6. Every other app's file is read as it always was."""
    passing = set()
    for path in sorted((REPO / "apps").glob("*/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("write_failure") \
                    and any(k.arg == "page_facts" for k in node.keywords):
                passing.add(path.parent.name)
    assert passing == {"anthem"}, passing
