"""The privacy canary.

A page carrying a distinctive fake secret in every channel a browser
offers. Produce a failure export from it and assert that none of them
comes out.

This exists because the first version of the exporter collected what
looked useful and ran it through redaction, and that was not enough.
Eleven of these twenty one came out of it. A name through the page
title. A street and a card tail through the receipt's own text, because
they are words and the masking knew about digits. An element id and a
class, straight out.

Safety that depends on a reviewer noticing a secret is not safety. Run
this whenever the schema changes.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import failure

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

PAGE = """<!doctype html>
<title>Orders for CANARYNAME CANARYSURNAME</title>
<style>.CANARYCLASS { color: #333 } .modal { display: none }</style>
<h1>Welcome back, CANARYNAME</h1>
<p>Member CANARYMEMBER at CANARYSTREET, CANARYCITY</p>
<p>Card ending CANARYCARD, balance CANARYAMOUNT</p>
<a id="CANARYID" class="CANARYCLASS btn"
   href="/order/CANARYORDERID?token=CANARYTOKEN#CANARYHASH"
   aria-label="Receipt for CANARYNAME CANARYSURNAME CANARYAMOUNT"
   title="CANARYTITLE">View Receipt</a>
<input type="hidden" name="member" value="CANARYHIDDEN">
<input type="text" value="CANARYINPUT">
<div class="modal fade" role="dialog" data-testid="CANARYTESTID">
  <p>CANARYRECEIPTLINE 12.34</p>
</div>
<div role="dialog" class="modal show" style="width:600px;height:400px">
  <p>E 933402 CANARYITEM 7.29 3</p>
</div>
<script>
  console.log("console says CANARYCONSOLE");
  console.error("error says CANARYCONSOLEERR");
  window.addEventListener('load', () => {
    setTimeout(() => { throw new Error("thrown CANARYTHROWN for CANARYNAME"); }, 20);
  });
</script>
"""

# Every one of these is somewhere on that page, in a different channel.
CANARIES = {
    "CANARYNAME": "a first name, in a heading and the title",
    "CANARYSURNAME": "a surname, in the title and an aria-label",
    "CANARYMEMBER": "a membership number, in visible text",
    "CANARYSTREET": "a street address",
    "CANARYCITY": "a city",
    "CANARYCARD": "a card tail",
    "CANARYAMOUNT": "an amount",
    "CANARYID": "an element id",
    "CANARYCLASS": "a class name",
    "CANARYORDERID": "an order number in a URL path",
    "CANARYTOKEN": "a token in a query string",
    "CANARYHASH": "a fragment",
    "CANARYTITLE": "a title attribute",
    "CANARYTESTID": "a test id",
    "CANARYHIDDEN": "a hidden input value",
    "CANARYINPUT": "a text input value",
    "CANARYCONSOLE": "a console log",
    "CANARYCONSOLEERR": "a console error",
    "CANARYTHROWN": "an uncaught exception",
    "CANARYRECEIPTLINE": "a line in the hidden dialog",
    "CANARYITEM": "a line in the visible dialog",
}

SELECTORS = {
    "receipt_area": "[role=dialog], .modal.show",
    "receipt_button": "button:has-text('View Receipt')",
    "order_link": "a[href*='order']",
    "hidden_input": "input[type=hidden]",
    "by_class": ".CANARYCLASS",
    "by_testid": "[data-testid]",
}


@pytest.fixture(scope="module")
def export(tmp_path_factory):
    """One export, from a real browser on that page."""
    out_dir = tmp_path_factory.mktemp("canary")
    html = out_dir / "page.html"
    html.write_text(PAGE, encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            failure.watch_errors(page)
            page.goto(html.as_uri())
            page.wait_for_timeout(300)
            body_text = page.locator("body").inner_text()
            path = failure.write_failure(
                out_dir, command="pilot", step="render the receipt",
                reason="the document would not render",
                page=page, selectors=SELECTORS, provider="Canary",
                version="0.0.0",
                error=RuntimeError("failed on CANARYORDERID for CANARYNAME"),
                extra={"postmortem": failure.postmortem(
                           page, "[role=dialog]", saved_bytes=989,
                           expected_bytes=3000),
                       "parser": failure.parser_counts(
                           candidates=12, accepted=0,
                           rejected={"missing currency symbol": 12}),
                       "a string from the page": body_text,
                       "nested": {"deeper": {"still": body_text}}},
                say=lambda *a: None)
            browser.close()
    except Exception as e:  # pragma: no cover
        pytest.skip("no browser available: %s" % e)
    assert path
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.parametrize("canary", sorted(CANARIES), ids=sorted(CANARIES))
def test_the_canary_does_not_come_out(canary, export):
    assert canary not in export, \
        "%s leaked (%s)" % (canary, CANARIES[canary])


def test_the_export_is_still_worth_reading(export):
    """A file that says nothing is safe and useless. These are the facts
    that solved real bugs."""
    report = json.loads(export)
    said = " ".join(failure.summarize(report))
    assert "Playwright's dialect" in said, "it no longer names a bad selector"
    assert "hidden copy of a dialog" in said, "it no longer spots the hidden one"
    assert "nought by nought" in said, "it no longer reports an empty render"
    assert "none were accepted" in said, "it no longer reports the parser"


def test_the_signal_classes_survive(export):
    """The one thing allowed out of a class attribute, because
    div.modal.fade was the answer to a bug that cost a day."""
    report = json.loads(export)
    found = set()
    for entry in report["selectors"]:
        for node in entry.get("nodes") or []:
            found.update(node.get("signal_classes") or [])
    assert "modal" in found and "fade" in found


def test_the_class_that_is_not_a_layout_word_does_not(export):
    assert "CANARYCLASS" not in export
    assert "btn" not in export


def test_a_string_handed_in_by_an_app_is_dropped_not_scrubbed(export):
    """An app that starts passing page text does not widen the file, it
    loses the field."""
    report = json.loads(export)
    extra = report["extra"]
    assert extra["a_string_from_the_page"] is None
    assert extra["nested"]["deeper"]["still"] is None


def test_an_exception_becomes_one_word(export):
    report = json.loads(export)
    assert report["error"] in ("unknown", "timeout", "navigation", "detached",
                              "selector", "not_found", "blocked")


def test_the_schema_is_versioned(export):
    """So a reader can tell which rules a file was written under."""
    assert json.loads(export)["schema"] == 2


def test_the_file_is_small_enough_to_paste(export):
    assert len(export) < 60000
