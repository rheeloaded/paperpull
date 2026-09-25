"""The shape of the page reaches the control, even inside a component.

A slot's children are its fallback content. What a person sees in a slot,
and what a click inside a web component lands on, is what was assigned to
it, so a walk that used the children stopped at the slot and the shape
had no control in it at all. It also said it was complete. Salesforce
Lightning, which PG&E runs on, is built of exactly these.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.recorder import Recorder  # noqa: E402

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

PAGE = """<!doctype html><title>t</title>
<x-card><span role="button" id="go">Statements</span></x-card>
<script>
  customElements.define('x-card', class extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({mode: 'open'}).innerHTML =
        '<section><div class="frame"><slot></slot></div></section>';
    }
  });
</script>"""


def _find(node, pred, out=None):
    out = [] if out is None else out
    if pred(node):
        out.append(node)
    for c in node.get("children") or []:
        _find(c, pred, out)
    return out


def test_a_control_slotted_into_a_component_is_reached(tmp_path):
    html = tmp_path / "p.html"
    html.write_text(PAGE, encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(html.as_uri())
            rec = Recorder(page, is_safe_url=lambda url: True)
            rec.start()
            page.click("#go")
            page.wait_for_timeout(300)
            report = rec.stop()
            browser.close()
    except Exception as e:  # pragma: no cover
        pytest.skip("no browser available: %s" % e)

    shape = report["steps"][0]["structure"]
    targets = _find(shape["root"], lambda n: n.get("target"))
    assert len(targets) == 1 and targets[0]["tag"] == "span"
    assert _find(shape["root"], lambda n: n.get("tag") == "slot")
    assert shape["truncated"] is False
