"""Where the site layer stops and the interceptor takes over.

Navy Federal is the awkward one. The PDF arrives as a blob a tab minted
for itself, an inactivity modal keeps appearing while that tab opens,
and a full archive is hundreds of statements so every tab left behind
is a tab left behind three hundred times.

The old code handled all of that by hand, including sweeping away blob
tabs from earlier statements before it clicked, because otherwise it
read the previous statement's blob as this one. These pin down that the
handover keeps every one of those properties.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import navyfederal_site as site
from paperpull_core import delivery


class _Btn:
    def __init__(self, n=1):
        self.n, self.clicks = n, []
        self.first = self

    def count(self):
        return self.n

    def nth(self, i):
        return self

    def locator(self, sel):
        return self

    def filter(self, **kw):
        return self

    def click(self, **kw):
        self.clicks.append(1)


class _Page:
    def __init__(self, btn=None):
        self.url = "https://www.navyfederal.org/statements"
        self._btn = btn if btn is not None else _Btn()
        self.waits = 0

    def locator(self, sel):
        return self._btn

    def wait_for_timeout(self, ms):
        self.waits += 1

    def get_by_role(self, *a, **k):
        return _Btn(n=0)


def ready(monkeypatch, btn=None):
    monkeypatch.setattr(site, "expand_only", lambda p, a: True)
    monkeypatch.setattr(site, "dismiss_timeout", lambda p: None)
    monkeypatch.setattr(site, "year_select", lambda p: (None, []))
    return _Page(btn)


def test_the_route_hands_over_and_does_not_click(monkeypatch):
    btn = _Btn()
    req = site.statement_request(ready(monkeypatch, btn), "Checking", "2026-07-24")
    assert req is not None
    assert btn.clicks == [], "the route clicked instead of handing over"
    req.trigger()
    assert btn.clicks == [1]


def test_the_modal_is_dismissed_while_the_blob_tab_opens(monkeypatch):
    """The inactivity modal reappears while the tab is opening and
    delays it. Without this the wait times out on a provider that was
    about to answer."""
    dismissed = []
    monkeypatch.setattr(site, "expand_only", lambda p, a: True)
    monkeypatch.setattr(site, "year_select", lambda p: (None, []))
    monkeypatch.setattr(site, "dismiss_timeout", lambda p: dismissed.append(1))
    req = site.statement_request(_Page(), "Checking", "2026-07-24")
    assert req.while_waiting is not None
    before = len(dismissed)
    req.while_waiting()
    assert len(dismissed) == before + 1


def test_the_blob_tab_is_closed_once_it_is_read(monkeypatch):
    """Three hundred statements is three hundred tabs otherwise."""
    req = site.statement_request(ready(monkeypatch), "Checking", "2026-07-24")
    assert req.close_new_tabs is True


def test_the_hint_says_this_provider_answers_in_a_tab(monkeypatch):
    req = site.statement_request(ready(monkeypatch), "Checking", "2026-07-24")
    assert req.hints == (delivery.TAB,)
    assert delivery._order(req.hints)[0] == delivery.TAB
    # A hint reorders and never restricts, so a Navy Federal that starts
    # firing an ordinary download still works.
    assert set(delivery._order(req.hints)) == {delivery.DOWNLOAD,
                                               delivery.TAB, delivery.FOLDER}


def test_the_statement_is_checked_against_its_date(monkeypatch):
    """A row carries an account and a date. The account is the same on
    every statement in the group, so only the date tells two apart."""
    req = site.statement_request(ready(monkeypatch), "Checking", "2026-07-24")
    assert req.expect.date == "2026-07-24"
    assert sorted(req.expect.strong()) == ["date"]


def test_a_row_that_is_not_there_hands_over_nothing(monkeypatch):
    assert site.statement_request(ready(monkeypatch, _Btn(n=0)),
                                  "Checking", "2026-07-24") is None


def test_sweeping_stale_blob_tabs_is_no_longer_this_apps_job(monkeypatch):
    """The old code closed leftover blob tabs before clicking, or it
    read the previous statement's blob as this one. The interceptor
    collects only tabs opened after it starts listening, so the sweep
    became unnecessary rather than being dropped."""
    import inspect

    source = inspect.getsource(site.statement_request)
    assert "close()" not in source
    assert "blob:" not in source


def test_the_hand_rolled_blob_reader_is_gone(monkeypatch):
    """Reading a blob now happens in capture.fetch_as_b64, which is the
    same trick in one place rather than eleven."""
    assert not hasattr(site, "_NFCU_BLOB_FETCH")
