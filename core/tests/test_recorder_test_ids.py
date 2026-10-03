"""A click on the words inside a control marked only with a test id is a step.

American Family marks its controls with data-cy and nothing else, no role
and no link. A click lands on the words inside, a span, and the recorder
walked up looking for a role or a data-testid, found neither, and threw the
click away as the mouse wandering. His recording of the billing tab kept one
click of seven (#45). In a real browser, since where a click lands is the
browser's doing. Every page here is made up."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://example.test"

PAGE = """<!doctype html><html><body>
<nav><div data-cy="billing-nav"><span>Billing &amp; Payments</span></div></nav>
<section>
  <div data-test="view-bill"><div><span><b>View</b> bill</span></div></div>
  <div data-cy="statement-8f3a9c21d0e1"><span>Statement for September</span></div>
  <div data-qa="policy-card"><span>Auto policy</span></div>
  <p>Your bill is due on the fifteenth.</p>
  <div><span>Nothing to see</span></div>
</section>
</body></html>"""

# Found by where they sit, not by an id of their own, since his page's words
# carry none, and an element with a stable id was always kept.
BP = "nav span"
DEEP = "[data-test='view-bill'] b"
HASHY = "[data-cy^='statement-'] span"
QA = "[data-qa] span"


@pytest.fixture()
def page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=PAGE))
    pg = ctx.new_page()
    pg.goto("%s/billing" % HOST)
    yield pg
    browser.close()
    driver.stop()


def _record(page, *selectors):
    rec = recorder.Recorder(page, is_safe_url=lambda u: (u or "").startswith(HOST),
                            provider="Testco")
    rec.start()
    for sel in selectors:
        page.locator(sel).click()
        page.wait_for_timeout(300)
    return rec.stop()


def _words(report) -> str:
    """Every string in a recording, keys and values at any depth, one to a
    line, and none of its numbers. A page's words would reach the file as
    text, in a label or a locator, while a step's time is a number from the
    page's clock that can hold any four digits."""
    out = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(report)
    return "\n".join(out)


def test_the_words_inside_a_data_cy_control_are_a_step(page):
    report = _record(page, BP)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "billing-nav"}
    assert report["dropped"]["unresolved"] == 0


def test_a_control_a_few_levels_above_the_click_is_found(page):
    report = _record(page, DEEP)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "view-bill"}


def test_every_kind_of_test_id_marks_a_control(page):
    report = _record(page, QA)
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "policy-card"}


def test_a_changeable_test_id_is_dropped_and_its_words_never_written(page):
    """A generated id is no good to find the element by next time, and its
    words may be a section of an account page, so the click is dropped as
    one that cannot be named (review of 0.41.0)."""
    report = _record(page, HASHY)
    assert report["steps"] == []
    assert report["dropped"]["unresolved"] == 1
    assert "September" not in json.dumps(report)


def test_a_paragraph_or_plain_words_are_still_the_mouse_wandering(page):
    report = _record(page, "text=Your bill is due", "text=Nothing to see")
    assert report["steps"] == []
    assert report["dropped"]["unresolved"] == 2


def test_his_billing_tab_keeps_every_click(page):
    """Seven clicks of his, as near as this page can have them, of which the
    recorder kept one."""
    report = _record(page, BP, DEEP, HASHY, QA)
    assert [st["locator"] for st in report["steps"]] == [
        {"how": "testid", "value": "billing-nav"}, {"how": "testid", "value": "view-bill"},
        {"how": "testid", "value": "policy-card"}]
    assert all(st["label"] == "" for st in report["steps"]), "found by its id, never its words"


def test_a_framework_prefix_counts_only_at_the_start():
    """Angular's ng- and styled-components' sc- anywhere in a value took
    "billing-nav" and "desc-field" for generated ids."""
    import re
    source = re.search(r"const HASHY = /(.*?)/i;", recorder._CAPTURE_JS).group(1)
    hashy = re.compile(source, re.I)
    for kept in ("billing-nav", "desc-field", "pending-payments", "statement-row", "view-bill"):
        assert not hashy.search(kept), kept
    for generated in ("ng-tns-c12-3", "css-1a2b3c", "sc-bdVaJa", "jsx-123", "emotion-0",
                      "statement-8f3a9c21d0e1", "row-1234567"):
        assert hashy.search(generated), generated


# -- from the pre-release review of 0.41.0, what a recording may carry ------------

# The pages below keep a clock whose every reading holds 5678 and 4821, the
# private digits they carry, while the milliseconds still pass as they do.
# A step's time is the page's clock. On 2026-10-01 one read 1790875678992,
# and a check that looked in the recording's numbers as well as its words
# failed. Here every reading would fail such a check, not one in a thousand.
_CLOCK = """(() => {
  const real = Date.now.bind(Date), start = real();
  Date.now = () => 56784821000000 + (real() - start);
})();"""

SECTION = """<!doctype html><html><body><main data-cy="billing-page">
<section data-cy="policy-summary"><h2>Auto policy</h2>
<p>Policy 00-1234-5678-90, named insured Invented Person and Another Person,
2019 Invented Sedan, 1417 Example Avenue, Anytown</p></section>
<table><tr role="row"><td>Checking ending in 4821</td><td>Balance 1,234.56</td></tr></table>
</main></body></html>"""


@pytest.fixture()
def section_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.add_init_script(_CLOCK)
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=SECTION))
    pg = ctx.new_page()
    pg.goto("%s/billing" % HOST)
    yield pg
    browser.close()
    driver.stop()


def test_a_click_inside_a_marked_section_never_writes_the_sections_words(section_page):
    """The click stopped at the section its site marks with data-cy, and the
    section's own words, names, a policy number and an address, became the
    step's label, in a file testers post publicly."""
    report = _record(section_page, "section p")
    [step] = report["steps"]
    assert step["locator"] == {"how": "testid", "value": "policy-summary"}
    assert step["label"] == ""
    text = _words(report)
    for private in ("Invented Person", "Another Person", "Example Avenue", "Sedan", "5678"):
        assert private not in text, private


def test_a_click_inside_a_row_is_the_row_and_never_its_words(section_page):
    report = _record(section_page, "tr td >> nth=1")
    [step] = report["steps"]
    assert step["locator"] == {"how": "role", "role": "row"}
    assert step["label"] == ""
    text = _words(report)
    assert "Balance" not in text and "4821" not in text


# -- from the second review of 0.41.0 ---------------------------------------------------

LABELED = """<!doctype html><html><body>
<section data-cy="policy-8f3a9c21d0e1" aria-label="Auto policy for Invented Person">
<p class="one">Coverage details</p></section>
<div role="region" aria-label="Accounts of Another Person"><p class="two">Balances</p></div>
<div role="listitem" aria-label="Policy 00-1234-5678 for Invented Person"><span class="three">Home</span></div>
<button aria-label="View bill"><span class="four">View</span></button>
</body></html>"""


@pytest.fixture()
def labeled_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.add_init_script(_CLOCK)
    ctx.route("%s/**" % HOST, lambda route: route.fulfill(
        status=200, content_type="text/html", body=LABELED))
    pg = ctx.new_page()
    pg.goto("%s/billing" % HOST)
    yield pg
    browser.close()
    driver.stop()


def test_a_containers_aria_label_is_never_written(labeled_page):
    """A section marked with a generated test id fell through to its
    aria-label, the policyholder's name in it, and 0.40.0 had dropped the
    click. A region or a list item named for an account holder is the same."""
    report = _record(labeled_page, ".one", ".two", ".three")
    text = _words(report)
    for private in ("Invented Person", "Another Person", "5678", "Auto policy for"):
        assert private not in text, private


def test_the_private_words_are_looked_for_in_every_string_and_no_number():
    """What the private words in this file are looked for in. A label's
    words and a locator's value are searched at any depth, and a step's time
    is not."""
    words = _words({"steps": [{"label": "Policy 00-1234-5678", "at": 56784821000123,
                               "locator": {"how": "testid", "value": "holder-4821"}}]})
    assert "Policy 00-1234-5678" in words and "holder-4821" in words
    assert "56784821000123" not in words


def test_a_controls_own_aria_label_is_still_its_name(labeled_page):
    report = _record(labeled_page, ".four")
    [step] = report["steps"]
    assert step["locator"] == {"how": "role", "role": "button", "name": "View bill"}
    assert step["label"] == "View bill"


def test_a_name_joined_into_an_id_is_pointed_out():
    """A click inside a marked container is kept by its test id, and a site
    can build one from a name, which the check for name-shaped words did
    not see through the dashes."""
    report = {"steps": [{"locator": {"how": "testid", "value": "holder-Invented-Person"}},
                        {"locator": {"how": "id", "value": "insured_Another_Person"}},
                        {"locator": {"how": "testid", "value": "view-bill"}}]}
    said = " ".join(recorder.concerns(report))
    assert "Invented Person" in said and "Another Person" in said
    assert "view bill" not in said.lower()


def test_a_name_after_a_dashed_word_is_still_pointed_out():
    """Read with its dashes as spaces, "Bill-To-John Smith" is "Bill To
    John", a control's words, and "John Smith" went unseen."""
    said = " ".join(recorder.concerns({"steps": [{"label": "Bill-To-John Smith"}]}))
    assert "John Smith" in said
