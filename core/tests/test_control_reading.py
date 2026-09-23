"""Reading the controls a click revealed.

The page is stood in for, because what matters here is the choosing: which
of the words that appeared is the one that finishes a download, and that
the app's own guard still has the last say.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core.controls import control_texts, second_step  # noqa: E402

PATTERN = re.compile(r"^\s*(download|download\s+pdf|regular\s+pdf|itemized\s+pdf|save)\s*$", re.I)


class FakeLoc:
    def __init__(self, texts, visible=True):
        self._texts = texts
        self._visible = visible

    def count(self):
        return len(self._texts)

    def nth(self, i):
        return FakeLoc([self._texts[i]], self._visible)

    def inner_text(self, timeout=None):
        return self._texts[0]

    def is_visible(self):
        return self._visible

    @property
    def first(self):
        return self


class FakePage:
    """Answers get_by_role the way Playwright does, with a name filter."""

    def __init__(self, by_role, visible=True):
        self.by_role = by_role
        self.visible = visible

    def get_by_role(self, role, name=None):
        texts = self.by_role.get(role, [])
        if name is not None:
            texts = [t for t in texts if name.match(t)]
        return FakeLoc(texts, self.visible)


def allow_all(_name):
    return True


# -- control_texts -------------------------------------------------------------

def test_it_gathers_every_role_and_tidies_the_words():
    page = FakePage({"button": ["  Download   PDF  "], "link": ["Statements"], "menuitem": ["Help"]})
    assert control_texts(page) == {"Download PDF", "Statements", "Help"}


def test_it_skips_blank_labels():
    page = FakePage({"button": ["", "   ", "Download"]})
    assert control_texts(page) == {"Download"}


def test_a_control_that_will_not_answer_does_not_stop_the_rest():
    class Grumpy(FakePage):
        def get_by_role(self, role, name=None):
            if role == "button":
                raise RuntimeError("detached")
            return super().get_by_role(role, name)
    page = Grumpy({"button": ["Download"], "link": ["Statements"]})
    assert control_texts(page) == {"Statements"}


# -- second_step ---------------------------------------------------------------

def test_it_finds_the_control_that_finishes_the_download():
    page = FakePage({"button": ["Download PDF"]})
    loc, text = second_step(page, {"Download PDF"}, PATTERN, allow_all)
    assert text == "Download PDF" and loc is not None


def test_the_plain_choice_is_preferred_over_the_other_one():
    """AT&T's menu offers Regular and Itemized. The bill is the regular
    one, and picking by chance would fetch a different document."""
    page = FakePage({"button": ["Regular PDF", "Itemized PDF"]})
    _loc, text = second_step(page, {"Itemized PDF", "Regular PDF"}, PATTERN, allow_all)
    assert text == "Regular PDF"


def test_words_that_do_not_finish_a_download_are_ignored():
    page = FakePage({"button": ["Cancel", "Close"]})
    assert second_step(page, {"Cancel", "Close"}, PATTERN, allow_all) == (None, "")


def test_the_app_guard_still_has_the_last_say():
    """It matches the pattern and is on the page, and the app still refuses
    it. The guard is not advisory."""
    page = FakePage({"button": ["Download"]})
    assert second_step(page, {"Download"}, PATTERN, lambda _n: False) == (None, "")


def test_something_that_is_not_visible_is_not_chosen():
    page = FakePage({"button": ["Download"]}, visible=False)
    assert second_step(page, {"Download"}, PATTERN, allow_all) == (None, "")


def test_nothing_appeared_at_all():
    page = FakePage({"button": ["Download"]})
    assert second_step(page, set(), PATTERN, allow_all) == (None, "")
