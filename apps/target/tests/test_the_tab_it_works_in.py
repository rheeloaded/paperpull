"""Target works in the tab Login left open on Target's own site, or else in a
tab of its own, and never in a tab of another site.

Its page() took the browser's first tab, whatever site it showed, read it
for the order list and then loaded it away to Target. It now takes the tab
on Target's site, and with none open a tab of its own. Each purchase asks
for the tab again, so a Target tab of the person's that is moved to another
site partway through a run is let go of, rather than loaded back onto Target
for the next purchase.

The browser here is a stand-in, so nothing is opened and nothing reaches
Target. Each tab notes every address it is sent to.
"""
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import target_receipts as app_mod
import target_site as site
from paperpull_core import tabs, testkit
from paperpull_core.models import ONLINE, Purchase

THEIRS = "https://www.target.com/orders"
ELSEWHERE = "https://www.elsewhere.example/inbox"


class Tab:
    def __init__(self, url, context):
        self.url, self.context, self.closed, self.loads = url, context, False, []

    def is_closed(self):
        return self.closed

    def goto(self, url, **_kw):
        self.loads.append(url)
        self.url = url

    def on(self, *_a, **_kw):
        return None

    remove_listener = once = on


class Context:
    def __init__(self, *urls):
        self.pages = [Tab(u, self) for u in urls]

    def new_page(self):
        tab = Tab("about:blank", self)
        self.pages.append(tab)
        return tab

    def add_init_script(self, *_a, **_kw):
        return None

    def on(self, *_a, **_kw):
        return None

    remove_listener = once = on


@pytest.fixture
def attached(tmp_path):
    """Target's own App, attached to a stand-in browser."""
    app = testkit.receipt_app(app_mod, tmp_path, cdp_url="http://127.0.0.1:9")

    def holding(*urls):
        app._context = Context(*urls)
        app._cdp_mode = True
        app._work_page = None
        return app._context
    return app, holding


def test_with_no_target_tab_it_works_in_a_tab_of_its_own(attached):
    app, holding = attached
    ctx = holding(ELSEWHERE)
    elsewhere = ctx.pages[0]
    page = app.page()
    assert page is not elsewhere and tabs.is_own(page)
    assert not elsewhere.loads


def test_the_target_tab_login_left_open_is_the_one_used(attached):
    app, holding = attached
    ctx = holding(ELSEWHERE, THEIRS)
    assert app.page() is ctx.pages[1]
    assert app.page() is ctx.pages[1], "and the next ask is answered with it again"


def test_a_target_tab_moved_elsewhere_partway_is_let_go_of(attached, monkeypatch):
    """The person moved their Target tab to another site after the first
    purchase. The second purchase is taken in a tab of the run's own, and
    their tab is never handed over again, nor loaded back onto Target."""
    app, holding = attached
    ctx = holding(THEIRS)
    theirs = ctx.pages[0]
    handed = []

    def process_one(self, page, purchase, dry_run=False):
        handed.append(page)
        if len(handed) == 1:
            theirs.url = ELSEWHERE

    monkeypatch.setattr(app_mod.App, "process_one", process_one)
    purchases = [Purchase(purchase_type=ONLINE, purchase_date="2026-06-%02d" % day,
                          order_number="90000000000000%d" % day) for day in (14, 15)]
    app.process_purchases(purchases)

    assert handed[0] is theirs
    assert handed[1] is not theirs and tabs.is_own(handed[1])
    assert urlsplit(theirs.url).hostname == "www.elsewhere.example" and not theirs.loads


def test_without_attaching_it_works_in_the_first_tab_of_its_own_browser(tmp_path):
    """An install with no cdp_url launches a browser of its own, every tab of
    which is the app's, and works in its first tab as it always did."""
    app = testkit.receipt_app(app_mod, tmp_path)
    app._context = Context(ELSEWHERE)
    app._cdp_mode = False
    assert app.page() is app._context.pages[0]
