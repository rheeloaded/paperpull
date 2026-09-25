"""A click inside a web component is recorded as what was clicked.

His second recording of American Family followed the billing tab it
opened, and every one of his six clicks there was thrown away as
unnameable (#45). A click that lands inside a shadow root reaches the
document's listener retargeted to the component that holds it, and a
component has no role and no text of its own, so the recorder saw a
nameless element and dropped it. What was really clicked is the first
element on the event's composed path.

In a real browser, because retargeting is the browser's doing and a fake
page cannot get it wrong the same way.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import recorder  # noqa: E402

HOST = "https://example.test"

PAGE = """
<h1>Billing</h1>
<bill-list></bill-list>
<odd-thing></odd-thing>
<script>
customElements.define('bill-list', class extends HTMLElement {
  constructor() {
    super();
    const root = this.attachShadow({mode: 'open'});
    root.innerHTML = '<span id="lbl">Bill for March</span>' +
      '<ul><li><button id="view">View bill</button></li>' +
      '<li><a id="dl" href="#" aria-labelledby="lbl">PDF</a></li></ul>';
  }
});
customElements.define('odd-thing', class extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'}).innerHTML = '<i style="display:inline-block;width:40px;height:20px"></i>';
  }
});
</script>
"""


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
        page.wait_for_timeout(500)
    return rec.stop()


def test_a_button_inside_a_component_is_recorded_by_its_name(page):
    report = _record(page, "bill-list >> #view")
    [step] = report["steps"]
    assert step["locator"] == {"how": "role", "role": "button", "name": "View bill"}
    assert step["where"] == {"in_shadow": True}
    assert report["dropped"]["unresolved"] == 0


def test_a_label_inside_the_same_component_names_its_control(page):
    report = _record(page, "bill-list >> #dl")
    [step] = report["steps"]
    assert step["locator"]["name"] == "Bill for March"


def test_a_click_that_still_cannot_be_named_says_what_it_landed_on(page):
    report = _record(page, "odd-thing >> i")
    assert report["steps"] == []
    assert report["dropped"]["unresolved"] == 1
    assert report["dropped"]["unresolved_on"] == {"i": 1}
    assert report["dropped"]["unresolved_where"] == {"in_shadow": 1}


def test_what_it_says_about_a_lost_click_is_counts_and_listed_names(page):
    report = _record(page, "odd-thing >> i")
    for kind, n in report["dropped"]["unresolved_on"].items():
        assert kind in recorder.STRUCTURE_TAGS and isinstance(n, int)
    for key, n in report["dropped"]["unresolved_where"].items():
        assert key in {"in_shadow", "in_frame", "in_opened_tab"} and isinstance(n, int)
    assert recorder.concerns(report) == []
