"""A receipt saved under a name the app was unsure of, told apart from one
set aside, and Review Names that never takes "keep" for a name.

On a real Target account a Try the newest few saved three receipts, one
under a name Target was unsure of. The panel said a document set aside sat
in the Manual Review folder, which was empty, since the receipt was filed
where it belonged and waited only for Review names. In Review names the
empty box read "Keep this name", and typed into four boxes it renamed four
receipts "... Keep This Name Invoice.pdf". And a provider whose records came
from before downloaded_ok was written showed Nothing saved yet over 67
receipts. Every name and number here is invented.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")
import run_result  # noqa: E402
from paperpull_core import renaming  # noqa: E402

GUI = Path(__file__).resolve().parents[1]
JS = (GUI / "static" / "app.js").read_text(encoding="utf-8")
# The mark a run is given, which its result line carries.
MARK = "0123456789abcdef" * 2
LINE = run_result.PREFIX + MARK + " %s"


def line(**counts):
    base = {"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 0}
    return LINE % json.dumps(dict(base, **counts))


def test_the_result_carries_receipts_to_name_and_refuses_more_than_were_counted():
    got = run_result.parse(line(manual_review=2, name_review=1), MARK)
    assert got["name_review"] == 1 and got["manual_review"] == 2 and got["attention"]
    # An install not refreshed yet sends none, which is none to name.
    assert run_result.parse(line(manual_review=1), MARK)["name_review"] == 0
    assert run_result.parse(line(manual_review=1, name_review=2), MARK) is None
    assert run_result.parse(line(name_review=-1), MARK) is None
    assert run_result.parse(line(name_review="1"), MARK) is None


def test_the_dialog_keeps_a_name_for_the_very_words_the_core_does():
    found = re.search(r"const KEEP_WORDS = new Set\(\[(.*?)\]\);", JS, re.S)
    assert found, "the dialog's list of words that keep a name"
    words = set(re.findall(r"'([^']*)'", found.group(1)))
    assert words == set(renaming.KEEP_WORDS)
    assert ".filter(a => a.id && a.summary && !keepsName(a.summary))" in JS


def test_an_empty_box_says_blank_keeps_the_name_and_never_reads_like_one():
    boxes = re.findall(r'placeholder="([^"]*)" \' \+\s*\'aria-label="\' \+ esc\(\'New summary', JS)
    assert boxes == ["Leave blank to keep this name"]
    assert 'placeholder="Keep this name"' not in JS


@pytest.mark.parametrize("typed, keeps", [
    ("Keep this name", True), ("keep this name.", True), ("  KEEP  ", True), ("Same", True),
    ("Leave blank to keep this name", True), ("leave blank", True),
    ("No change!", True), ("leave as is", True), ("Garden Hose", False), ("Keepsake Box", False),
    ("keeper", False), ("Same Day Delivery", False), ("q", False), ("", False), (None, False)])
def test_the_core_reads_words_that_keep_a_name(typed, keeps):
    assert renaming.keeps_name(typed) is keeps


def _progress(tmp_path, records):
    (tmp_path / "progress.json").write_text(json.dumps(records), encoding="utf-8")
    return [f["name"] for f in app_module._latest_saved(tmp_path)]


def test_latest_documents_counts_a_record_from_before_downloaded_ok(tmp_path):
    names = _progress(tmp_path, {
        "Online:1": {"state": "Completed", "pdf_filename": "2026-01-02 Shop Lamp Receipt.pdf",
                     "purchase_date": "2026-01-02"},
        "Online:2": {"state": "Completed", "downloaded_ok": True,
                     "pdf_filename": "2026-01-03 Shop Hose Receipt.pdf", "purchase_date": "2026-01-03"},
        # Said not saved, and a receipt set aside with no word either way.
        "Online:3": {"state": "Completed", "downloaded_ok": False,
                     "pdf_filename": "2026-01-04 Shop Rake Receipt.pdf", "purchase_date": "2026-01-04"},
        "Online:4": {"state": "Needs Manual Review",
                     "pdf_filename": "2026-01-05 Shop Pot Receipt.pdf", "purchase_date": "2026-01-05"},
    })
    assert names == ["2026-01-03 Shop Hose Receipt.pdf", "2026-01-02 Shop Lamp Receipt.pdf"]


# --- The run's outcome, worked out by the page's own code in a browser.

sync_api = pytest.importorskip("playwright.sync_api")
# The page as the desktop panel serves it, its placeholders filled in.
DESKTOP_PAGE = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
                .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=[
                "--disable-extensions", "--disable-sync", "--disable-background-networking",
                "--disable-component-update", "--no-first-run"])
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s"
                        % str(e).strip().splitlines()[0])
        tab = chromium.new_page()
        # The page from an invented address, and nothing else answered,
        # which is all the better, since only its functions are asked here.
        # At about:blank the page's script stops before its constants.
        def answer(route):
            if route.request.url == "http://panel.test/":
                route.fulfill(status=200, content_type="text/html", body=DESKTOP_PAGE)
            else:
                route.abort()
        tab.route("**/*", answer)
        tab.goto("http://panel.test/")
        yield tab
        chromium.close()


def outcome(page, **counts):
    result = dict({"manual_review": 0, "failed": 0, "validation_failures": 0, "new_files": 1,
                   "wrong_document": 0, "stopped": 0, "name_review": 0}, **counts)
    result["attention"] = True
    return page.evaluate("""(result) => {
        Object.assign(RUN, {result, code: '0', action: 'pilot', again: false, refused: '',
                            saved: ['2026-09-27 Shop Mixed Receipt.pdf'], provider: 'Shop',
                            kind: 'RECEIPT', lines: []});
        return runOutcome();
    }""", result)


def test_a_receipt_saved_under_an_unsure_name_points_to_review_names(page):
    o = outcome(page, manual_review=1, name_review=1)
    assert o["names"] and not o["aside"]
    assert "saved under a name PaperPull was unsure of. Review names gives each a better one." in o["say"]
    assert "Manual Review folder" not in o["say"]


def test_one_set_aside_still_points_to_the_manual_review_folder(page):
    o = outcome(page, manual_review=1)
    assert o["aside"] and not o["names"]
    assert "sits in the Manual Review folder" in o["say"] and "Review names" not in o["say"]
    both = outcome(page, manual_review=3, name_review=2)
    assert both["names"] and both["aside"]
    assert "2 receipts were saved under a name" in both["say"] and "Manual Review folder" in both["say"]
    assert "Finished, with 2 saved under a name to review, 1 set aside." in both["say"]


def test_an_invoice_put_aside_beside_a_name_to_review_still_points_to_the_folder(page):
    """Target sets aside an invoice that failed its check and counts it in
    validation_failures, while its order counts as saved under a name to
    review. The folder is offered as well as Review names."""
    o = outcome(page, manual_review=1, name_review=1, validation_failures=1)
    assert o["names"] and o["aside"]
    assert "Review names gives each a better one." in o["say"] and "Manual Review folder" in o["say"]


def test_a_failure_alone_sends_nobody_to_a_folder(page):
    o = outcome(page, failed=1)
    assert "Manual Review" not in o["say"] and "technical details" in o["say"]


def test_the_box_under_the_outcome_offers_review_names(page):
    box = JS[JS.index("if (o.attention && r) {"):]
    box = box[:box.index("if (RUN.failure) {")]
    assert 'data-do="review"' in box and "Review names</button>" in box
    assert "const folder = !SERVER && !inSample() && (o.aside || !o.names);" in box


def test_the_dialog_in_the_page_drops_what_keeps_a_name(page):
    kept = page.evaluate("""(typed) => typed.map(keepsName)""",
                         ["Keep this name", "keep", "Same.", "Garden Hose", "Keepsake Box"])
    assert kept == [True, True, True, False, False]
