"""Where the site layer stops and the interceptor takes over.

T-Mobile fires an ordinary download today, which is the simplest case
there is, and that is exactly why the split has to be pinned here. A
route that quietly went back to clicking and catching its own download
would pass every other test in this app.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tmobile_site as site


# -- the handover to the interceptor ------------------------------------------

class _Btn:
    def __init__(self, label="Download detailed bill", n=1):
        self.label, self.n, self.clicks = label, n, []
        self.first = self

    def count(self):
        return self.n

    def get_attribute(self, name, **kw):
        return self.label

    def inner_text(self, **kw):
        return self.label

    def scroll_into_view_if_needed(self, **kw):
        pass

    def click(self, **kw):
        self.clicks.append(1)


class _Page:
    def __init__(self, url="https://www.t-mobile.com/bill/historical", btn=None):
        self.url, self._btn = url, btn if btn is not None else _Btn()

    def get_by_role(self, role, name=None):
        return self._btn

    def evaluate(self, *a, **k):
        return None


def test_the_route_hands_over_a_request_and_does_not_click(monkeypatch):
    """The whole point of the split. The site layer stops at the control,
    so every way of catching a document can be armed before it fires."""
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    btn = _Btn()
    req = site.bill_request(_Page(btn=btn), "2026-08-12")
    assert req is not None
    assert btn.clicks == [], "the route clicked instead of handing over"
    assert callable(req.trigger)
    req.trigger()
    assert btn.clicks == [1]


def test_the_request_carries_the_bill_date_to_check_against(monkeypatch):
    """A history row shows no amount and no document number, so the date
    is the only fact there is."""
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    req = site.bill_request(_Page(), "2026-08-12")
    assert req.expect.date == "2026-08-12"
    assert sorted(req.expect.strong()) == ["date"]


def test_a_bill_with_no_control_hands_over_nothing(monkeypatch):
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    assert site.bill_request(_Page(btn=_Btn(n=0)), "2026-08-12") is None


def test_a_control_the_guard_refuses_hands_over_nothing(monkeypatch):
    """A route that handed over a forbidden control would have the
    interceptor press it, which is worse than the old shape rather than
    better."""
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    assert not site.is_safe_control("Cancel plan")
    assert site.bill_request(_Page(btn=_Btn("Cancel plan")), "2026-08-12") is None


def test_a_nonsense_date_hands_over_nothing(monkeypatch):
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    assert site.bill_request(_Page(), "not-a-date") is None


def test_the_hint_says_this_provider_fires_an_ordinary_download(monkeypatch):
    """A hint reorders how the race is read and never restricts it, so a
    T-Mobile that switches to an inline tab tomorrow still works."""
    from paperpull_core import delivery
    monkeypatch.setattr(site, "dismiss_overlay", lambda p: None)
    req = site.bill_request(_Page(), "2026-08-12")
    assert req.hints == (delivery.DOWNLOAD,)
    assert delivery._order(req.hints)[0] == delivery.DOWNLOAD
    assert set(delivery._order(req.hints)) == {
        delivery.DOWNLOAD, delivery.RESPONSE, delivery.TAB, delivery.FOLDER}


def test_a_date_that_splits_into_three_parts_but_is_not_a_date():
    """The guard used to cover only the unpacking. "not-a-date" splits
    into three parts too, so the failure came out of int() one line
    later and took the whole run down instead of skipping one bill."""
    assert site._btn_re_for("not-a-date") is None
    assert site._btn_re_for("2026-13-01") is None
    assert site._btn_re_for("2026-00-15") is None
    assert site._btn_re_for("2026-08-99") is None
    assert site._btn_re_for("") is None
    assert site._btn_re_for(None) is None
    assert site._btn_re_for("2026-08-12") is not None
