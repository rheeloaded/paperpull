"""A control that could not be read is not left out of the count.

A date two rows carry cannot be told apart by the date, so nothing is
pressed for it, and a revealed document whose name two controls carry is
not pressed either (#37). Both counts left out a control that could not
be read, as if it were not on the page, so of two rows the other one's
View Documents was pressed, and of two revealed documents the other one
was, and saved under this document's name.

Found by the census that followed CI run 36792330947, where E*TRADE passed
over a control that did not answer in time. Every row is invented and the
browser is refused the network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import statefarm_site as site
from paperpull_core.testkit import stall_reads
from test_row_documents_in_a_browser import PAGE, _drive, _one_row  # noqa: E402  its made-up rows

TWO_ROWS = [("03/14/2026", "Renewal Notice - 2017 Invented Roadster"),
            ("03/14/2026", "Renewal Notice - 12 Invented Lane"),
            ("05/08/2026", "Payment Receipt - Payment Receipt")]
TWINS = "Renewal Notice - 12 Invented Lane"


def _rows_with_guids():
    return PAGE % "".join(
        _one_row(when, doc, i, "openDoc('%s')" % doc).replace(
            "<button class='view'", "<button class='view' data-guid='view-%d'" % i)
        for i, (when, doc) in enumerate(TWO_ROWS))


def _one_row_two_documents():
    row = _one_row("03/14/2026", TWINS, 0, "openDoc('a')").replace(
        "return false\">%s</a>" % TWINS,
        "return false\" data-guid='doc-0'>%s</a> <a href='#' data-guid='doc-1' "
        "onclick=\"openDoc('b');return false\">%s</a>" % (TWINS, TWINS))
    return PAGE % row


@pytest.fixture()
def drive():
    opened = []

    def start(html):
        driver, browser, pg = _drive(html)
        opened.append((driver, browser))
        return pg
    yield start
    for driver, browser in opened:
        browser.close()
        driver.stop()


@pytest.mark.parametrize("stalled", ["view-0", "view-1"])
def test_a_row_whose_control_could_not_be_read_keeps_the_other_unpressed(drive, tmp_path, monkeypatch, stalled):
    pg = drive(_rows_with_guids)
    stall_reads(monkeypatch, {stalled}, locator=(), handle=("evaluate",), scripts=(site._NAME_AND_ROW_JS,))
    out, trace = tmp_path / "doc.pdf", []
    assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Homeowners",
                                  trace=trace), trace
    assert not out.exists()
    assert not [t for t in trace if t.get("note") == "clicked"], trace
    assert {"note": "a control on the page could not be read", "unread": 1,
            "so": "which row is this document's is not known, so none was pressed"} in trace, trace
    assert pg.locator("button.view[aria-expanded='true']").count() == 0


def test_two_revealed_documents_with_one_name_are_both_counted(drive, tmp_path):
    """The twin with nothing stalled, so the test below is about the stall."""
    pg = drive(_one_row_two_documents)
    out, trace = tmp_path / "doc.pdf", []
    assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Homeowners", trace=trace)
    assert {"note": "no revealed document was pressed",
            "why": "2 visible controls carry that name, and one is needed"} in trace, trace


def test_a_revealed_document_that_could_not_be_read_keeps_its_twin_unpressed(drive, tmp_path, monkeypatch):
    """Whether the second document is shown could not be read. It was left
    out, and the first was pressed as the one control carrying the name."""
    pg = drive(_one_row_two_documents)
    stall_reads(monkeypatch, {"doc-1"}, locator=(), handle=("is_visible",))
    out, trace = tmp_path / "doc.pdf", []
    assert not site.download_bill(pg, None, "2026-03-14", out, title="Renewal Notice - Homeowners", trace=trace)
    assert not out.exists()
    assert {"note": "no revealed document was pressed",
            "why": "a control carrying that name could not be read"} in trace, trace
