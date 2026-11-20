"""Which of the person's tabs a run attached to their browser works in.
Every value is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fakes import FakeTab, make_app  # noqa: E402
import traderepublic_docs as app_mod  # noqa: E402
from paperpull_core import tabs  # noqa: E402


class Context:
    def __init__(self, pages):
        self.pages = list(pages)
        self.opened = []

    def new_page(self):
        tab = FakeTab(url="about:blank")
        tab.context = self
        self.opened.append(tab)
        self.pages.append(tab)
        return tab


def attached(tmp_path, pages):
    app = make_app(tmp_path, None)
    del app.page  # the App's own page(), over a browser of invented tabs
    ctx = Context(pages)
    app.browser = lambda: ctx
    app._cdp_mode = True
    app._work_page = None
    app._requests = object()
    return app, ctx


def test_the_home_page_tab_is_taken_before_another_trade_republic_tab(tmp_path):
    other = FakeTab(url="https://app.traderepublic.com/settings")
    home = FakeTab()
    app, ctx = attached(tmp_path, [FakeTab(url="https://example.test/boards"), other, home])
    assert app_mod.App.page(app) is home and not ctx.opened


def test_a_trade_republic_tab_off_the_home_page_is_taken_and_then_stops_the_run(tmp_path):
    other = FakeTab(url="https://app.traderepublic.com/settings")
    app, ctx = attached(tmp_path, [other])
    assert app_mod.App.page(app) is other
    with pytest.raises(SystemExit):
        app._on_its_site()
    assert other.asked == [] and other.navigated == 0


@pytest.mark.parametrize("url", ["https://example.test/boards", "https://traderepublic.com/de-de",
                                 "https://app.traderepublic.com.example.test/boards"])
def test_another_sites_tab_is_never_taken(tmp_path, url):
    theirs = FakeTab(url=url)
    app, ctx = attached(tmp_path, [theirs])
    tab = app_mod.App.page(app)
    assert tab is not theirs and tabs.is_own(tab) and ctx.opened == [tab]
    with pytest.raises(SystemExit):
        app._on_its_site()
    assert theirs.asked == [] and tab.asked == [] and tab.navigated == 0


def test_a_closed_tab_is_never_taken(tmp_path):
    gone = FakeTab()
    gone.closed = True
    app, ctx = attached(tmp_path, [gone])
    assert app_mod.App.page(app) is not gone
