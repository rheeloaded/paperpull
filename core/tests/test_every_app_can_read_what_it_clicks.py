"""Nothing pages forward by clicking a control it cannot read.

The pagination selector matches, among other things, any element whose
class merely contains "next". An icon-only chevron carries no text and no
aria-label, so the label the blocklist was handed was the empty string, the
blocklist found nothing to object to, and the control was clicked blind on
a bank page.

Chase found this while being reviewed before its first run and fixed it in
Chase. Eight apps kept the version it was fixed out of, and PG&E arrived at
the same answer from the other direction by insisting the label says next.

The click is the part that matters, so these watch for it rather than
reading the source or trusting the return value.
"""
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]

# Found by what it does. Walmart calls its pagination _go_next_page, so
# looking for "def next_page" missed it, and so did the fix this test was
# written alongside. Its last resort was any element whose aria-label
# merely contains "Next", clicked without reading it, which on an orders
# page is as likely to be "Next day delivery" as the pagination.
PAGES_FORWARD = re.compile(r"^def (\w*next\w*page\w*|\w*page\w*next\w*)\s*\(",
                           re.M | re.I)


def paginators(app: Path) -> list:
    """Every function in this app that pages a list forward."""
    source = (app / ("%s_site.py" % app.name)).read_text(
        encoding="utf-8", errors="ignore")
    names = [m.group(1) for m in PAGES_FORWARD.finditer(source)]
    # has_next_page only looks, it does not click
    return [n for n in names if not n.startswith("has_")]


APPS = sorted(d for d in (REPO / "apps").iterdir()
              if d.is_dir() and (d / ("%s_site.py" % d.name)).exists()
              and paginators(d))

UNREADABLE = ["", "   ", "\n\t "]


class Control:
    """One pagination candidate, reporting whatever labels it was given."""

    def __init__(self, text="", aria=None):
        self.text, self.aria = text, aria
        self.clicked = 0

    def inner_text(self, timeout=None):
        return self.text

    def get_attribute(self, name):
        return self.aria if name in ("aria-label", "title", "label") else None

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def click(self, timeout=None):
        self.clicked += 1

    def scroll_into_view_if_needed(self, timeout=None):
        pass


def page_showing(control):
    """A page whose only pagination candidate is this control."""
    page = MagicMock()
    handle = MagicMock()
    handle.count.return_value = 1
    handle.first = control
    handle.nth.return_value = control
    page.locator.return_value = handle
    page.query_selector_all.return_value = [control]
    page.querySelectorAll = page.query_selector_all
    return page


def run_each(site, app: Path, page):
    """Every one of this app's paginators, against the same page."""
    for name in paginators(app):
        fn = getattr(site, name, None)
        if fn is None:
            continue
        try:
            fn(page)
        except Exception:
            pass


def site_of(app: Path):
    for name in [m for m in list(sys.modules)
                 if m.endswith("_site") or m == "storage"]:
        del sys.modules[name]
    sys.path.insert(0, str(app))
    try:
        return importlib.import_module("%s_site" % app.name)
    finally:
        sys.path.pop(0)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
@pytest.mark.parametrize("label", UNREADABLE, ids=lambda s: repr(s))
def test_a_control_with_no_readable_label_is_not_clicked(app, label):
    site = site_of(app)
    control = Control(text=label, aria=label)
    try:
        run_each(site, app, page_showing(control))
    except Exception:
        pass
    assert control.clicked == 0, \
        "%s clicked a control whose label is %r" % (app.name, label)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_a_control_that_commits_something_is_still_not_clicked(app):
    """The check this one grew out of, which was never the problem here but
    would be the next one if a label check replaced the blocklist."""
    site = site_of(app)
    for label in ("Pay now", "Place Order", "Manage AutoPay"):
        control = Control(text=label, aria=label)
        try:
            run_each(site, app, page_showing(control))
        except Exception:
            pass
        assert control.clicked == 0, \
            "%s clicked %r to page forward" % (app.name, label)


@pytest.mark.parametrize("app", APPS, ids=lambda d: d.name)
def test_an_ordinary_next_control_is_still_clicked(app):
    """A guard that refuses the real Next control stops the run finding the
    older pages, which loses documents quietly, so this is the other half."""
    site = site_of(app)
    clicked = 0
    for label in ("Next", "Next page", ">"):
        control = Control(text=label, aria="Next")
        try:
            run_each(site, app, page_showing(control))
        except Exception:
            pass
        clicked += control.clicked
    assert clicked, "%s pages forward at none of Next, Next page or >" % app.name
