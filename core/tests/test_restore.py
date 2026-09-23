"""Putting the page back, against the bug that made it necessary.

Saving a document takes everything except the document off the screen.
On a provider that navigates between documents that is free, because the
next page load throws it away. On one that does not, the second document
is looked for on a page where nothing can be clicked, and from outside
that is indistinguishable from a page that did not load.

It cost two live runs to find. These run a real browser and do the same
thing on purpose.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import restore as R
from paperpull_core.journal import Journal

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="needs a browser").sync_playwright

PAGE = """<!doctype html>
<title>A shop</title>
<body style="margin: 8px">
<nav id="nav">the shop</nav>
<main id="list"><a href="#a">row one</a><a href="#b">row two</a></main>
<div id="dialog" style="width: 300px; height: 200px">the receipt</div>
</body>
"""

# What an isolation does. Hides the page behind the dialog, locks
# scrolling, and leaves both that way.
ISOLATE = """() => {
  for (const el of document.querySelectorAll('body > *')) {
    if (el.id !== 'dialog') el.style.display = 'none';
  }
  document.body.style.overflow = 'hidden';
  document.documentElement.style.overflow = 'hidden';
}"""

COUNT = """() => {
  let visible = 0;
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(el);
    if (s.display !== 'none' && s.visibility !== 'hidden') visible += 1;
  }
  return {visible: visible,
          overflow: getComputedStyle(document.body).overflow,
          body_style: document.body.getAttribute('style'),
          nav_style: document.getElementById('nav').getAttribute('style'),
          dialog_style: document.getElementById('dialog').getAttribute('style')};
}"""


@pytest.fixture()
def page(tmp_path):
    html = tmp_path / "page.html"
    html.write_text(PAGE, encoding="utf-8")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            p = browser.new_page()
            p.goto(html.as_uri())
            yield p
            browser.close()
    except Exception as e:  # pragma: no cover
        pytest.skip("no browser available: %s" % e)


def test_without_it_the_page_stays_hidden(page):
    """The bug, reproduced. Nothing here is put back."""
    before = page.evaluate(COUNT)
    assert before["visible"] >= 4
    page.evaluate(ISOLATE)
    after = page.evaluate(COUNT)
    assert after["visible"] == 1, "only the dialog is left"
    assert after["overflow"] == "hidden"


def test_with_it_the_page_comes_back(page):
    before = page.evaluate(COUNT)
    with R.restoring(page) as r:
        page.evaluate(ISOLATE)
        assert page.evaluate(COUNT)["visible"] == 1
    after = page.evaluate(COUNT)
    assert after["visible"] == before["visible"]
    assert after["overflow"] == before["overflow"]
    assert r.result["ok"] is True


def test_an_element_that_had_no_style_gets_none_back(page):
    """Not an empty one. A page can tell the difference, and so can the
    next person reading its markup."""
    assert page.evaluate(COUNT)["nav_style"] is None
    with R.restoring(page):
        page.evaluate(ISOLATE)
    assert page.evaluate(COUNT)["nav_style"] is None


def test_an_element_that_had_a_style_gets_that_one_back(page):
    was = page.evaluate(COUNT)["dialog_style"]
    assert "300px" in was
    with R.restoring(page):
        page.evaluate("() => { document.getElementById('dialog')"
                      ".style.width = '9999px'; }")
    assert page.evaluate(COUNT)["dialog_style"] == was


def test_the_page_comes_back_even_when_the_capture_raises(page):
    """The case that matters. A run that fails on one document and
    leaves the page hidden fails on every document after it, for a
    reason that has nothing to do with them."""
    before = page.evaluate(COUNT)["visible"]
    with pytest.raises(RuntimeError):
        with R.restoring(page):
            page.evaluate(ISOLATE)
            raise RuntimeError("the render blew up")
    assert page.evaluate(COUNT)["visible"] == before


def test_it_never_swallows_the_thing_that_went_wrong(page):
    with pytest.raises(ValueError, match="the real problem"):
        with R.restoring(page):
            raise ValueError("the real problem")


def test_it_says_whether_the_putting_back_worked(page):
    with R.restoring(page) as r:
        page.evaluate(ISOLATE)
    assert r.result["ok"] is True
    assert r.result["restored"] > 4
    assert r.result["changed"] >= 3, "it knows which ones it had to change"
    assert r.result["locked_after"] is False


def test_it_notices_when_the_page_is_still_locked(page):
    """A stylesheet rule, rather than an inline style, is outside what
    this remembers. Saying so is better than claiming success."""
    page.evaluate("() => { const s = document.createElement('style');"
                  " s.textContent = 'body { overflow: hidden }';"
                  " document.head.appendChild(s); }")
    with R.restoring(page) as r:
        page.evaluate(ISOLATE)
    assert r.result["locked_after"] is True
    assert r.result["ok"] is False


def test_the_journal_records_whether_it_worked(page):
    j = Journal(page)
    with R.restoring(page, journal=j):
        page.evaluate(ISOLATE)
    entry = j.entries[-1]
    assert entry["kind"] == "result"
    assert entry["outcome"] == "restore the page"
    assert entry["facts"]["restored"] > 4


def test_the_journal_records_a_failure_too(page):
    page.evaluate("() => { const s = document.createElement('style');"
                  " s.textContent = 'body { overflow: hidden }';"
                  " document.head.appendChild(s); }")
    j = Journal(page)
    with R.restoring(page, journal=j):
        page.evaluate(ISOLATE)
    assert j.entries[-1]["outcome"] == "could not put the page back"


def test_what_it_remembers_is_not_in_the_markup(page):
    """A property and not an attribute, so nothing about the page
    changes and nothing new turns up in its markup."""
    R.snapshot(page)
    html = page.evaluate("() => document.documentElement.outerHTML")
    assert "ppStyle" not in html
    assert "data-pp" not in html


def test_a_second_snapshot_does_not_overwrite_the_first(page):
    """Two captures in a row must not leave the second remembering the
    hidden page as the way things were."""
    before = page.evaluate(COUNT)["visible"]
    R.snapshot(page)
    page.evaluate(ISOLATE)
    R.snapshot(page)
    R.restore(page)
    assert page.evaluate(COUNT)["visible"] == before


def test_nothing_it_reports_is_text_from_the_page(page):
    with R.restoring(page) as r:
        page.evaluate(ISOLATE)
    body = json.dumps(r.result)
    assert "shop" not in body and "receipt" not in body and "row" not in body
    for value in r.result.values():
        assert isinstance(value, (int, bool)), value


# -- it may never make things worse -------------------------------------------

def test_a_page_that_raises_does_not_stop_a_capture():
    class Hostile:
        def evaluate(self, *a, **k):
            raise RuntimeError("Execution context was destroyed")

    assert R.snapshot(Hostile()) == 0
    out = R.restore(Hostile())
    assert out["ok"] is False
    assert out["evaluation"] == "detached"

    with R.restoring(Hostile()) as r:
        pass
    assert r.result["ok"] is False
