"""Reading a month off the page, filing it, the control guard, and the two presses that go through it. Every value here is made up."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ibkr_site as site
from paperpull_core import pressing


# ---- reading and filing a month

def test_a_month_label_and_a_month_code_are_read_and_anything_else_is_not():
    assert site.parse_month_label("September, 2026") == (2026, 9)
    assert site.parse_month_label(" january 2020 ") == (2020, 1)
    assert site.parse_month_label("Q3 2026") is None and site.parse_month_label("13, 2026") is None and site.parse_month_label("") is None
    assert site.parse_month_code("202609") == (2026, 9) and site.parse_month_code("string:202601") == (2026, 1)
    assert site.parse_month_code("202613") is None and site.parse_month_code("2026") is None


def test_a_month_is_filed_under_its_last_day():
    assert site.month_end_iso(2026, 2) == "2026-02-28" and site.month_end_iso(2024, 2) == "2024-02-29" and site.month_end_iso(2026, 12) == "2026-12-31"


def test_a_month_becomes_a_statement_titled_by_its_account():
    cat, date, period, title = site.classify_document(dict(year=2026, month=9, account_id="U1234567"))
    assert (cat, date, period, title) == ("Statement", "2026-09-30", "2026-09", "Activity Statement - Account U1234567")
    assert site.classify_document(dict(year=2026, month=9))[3] == "Activity Statement - Account"


def test_a_file_named_for_another_month_is_not_taken_and_one_with_no_such_name_passes():
    assert site.named_month_matches("U1234567_202609_202609.pdf", "202609")
    assert not site.named_month_matches("U1234567_202608_202608.pdf", "202609")
    assert not site.named_month_matches("U1234567_202608_202609.pdf", "202609")      # a span is not one month
    assert site.named_month_matches("statement.pdf", "202609")


# ---- the guard

HOSTILE = ["Trade", "Deposit Funds", "Withdraw", "Transfer Funds", "Convert Currency", "Pay now", "Update your statement delivery, contact support",
           "Statement delivery settings", "Change statement preferences", "Open a new account", "Cancel statement", "Request a statement", "Delete statement",
           "Download statement and subscribe", "Orders & Trades", "Monthly Activity Statement delivery", "Log out", "Sign in"]


@pytest.mark.parametrize("label", HOSTILE)
def test_a_control_that_moves_money_or_changes_anything_is_refused(label):
    assert not site.is_safe_control(label)


def test_only_a_document_action_passes_and_an_empty_or_unreadable_label_fails_closed():
    assert site.is_safe_control("Download PDF") and site.is_safe_control("Run Activity Statement")
    assert not site.is_safe_control("") and not site.is_safe_control(None) and not site.is_safe_control("Info")
    assert not site.is_safe_control("Download PDF Trade")                              # a no-break space folds to a space and the forbidden word is found


def test_the_core_guard_sees_what_the_local_words_do_not():
    assert site.is_money_control("") and site.is_money_control("Deposit")
    assert not site.is_money_control("statement period January, 2026 Monthly")


# ---- the two presses

class El:
    def __init__(self, label="", text=""):
        self._label, self._text = label, text

    def get_attribute(self, name):
        return self._label if name == "aria-label" else None

    def inner_text(self, timeout=0):
        return self._text

    def is_visible(self):
        return True


class Many:
    def __init__(self, el):
        self.first = el
        self._el = el

    def count(self):
        return 1


class Page:
    def __init__(self, button):
        self._button = button

    def get_by_role(self, role, name=None):
        return Many(self._button)

    def wait_for_timeout(self, ms):
        pass

    def expect_download(self, timeout=0):
        class Ctx:
            def __enter__(s):
                return type("I", (), {"value": None})()

            def __exit__(s, *a):
                raise TimeoutError("no download began")                         # what the browser does when a press brings no file
        return Ctx()


@pytest.fixture
def presses(monkeypatch):
    seen = []
    monkeypatch.setattr(site.pressing, "click", lambda page, loc, **kw: seen.append(kw["what"]))
    monkeypatch.setattr(site, "ensure_statements", lambda page: True)
    monkeypatch.setattr(site, "_clear_stray_dialog", lambda page: None)
    monkeypatch.setattr(site, "choose_monthly", lambda page: True)
    monkeypatch.setattr(site, "close_dialog", lambda page: None)
    return seen


def open_dialog(monkeypatch, label):
    state = {"open": False}
    monkeypatch.setattr(site, "dialog_is_open", lambda page: state["open"])
    monkeypatch.setattr(site, "_wait_for_run_control", lambda page: El(label=label))
    monkeypatch.setattr(site.pressing, "click", lambda page, loc, **kw: (state.__setitem__("open", True), PRESSED.append(kw["what"])))
    PRESSED.clear()
    return site.open_activity_dialog(Page(None))


PRESSED = []


def test_the_run_control_of_the_activity_row_is_pressed(presses, monkeypatch):
    assert open_dialog(monkeypatch, "Run") is True
    assert PRESSED == ["the Run control of the Activity Statement row"]


def test_a_run_control_the_guard_refuses_is_never_pressed(presses, monkeypatch):
    # The row's own words are folded in, so a control whose own label says money is refused although the row says Activity Statement.
    assert open_dialog(monkeypatch, "Transfer Funds") is False
    assert PRESSED == []


def month_select(monkeypatch):
    class Sel:
        def select_option(self, label=None, timeout=0):
            pass
    monkeypatch.setattr(site, "month_select", lambda page: Sel())
    monkeypatch.setattr(site, "open_activity_dialog", lambda page: True)


def test_the_download_button_is_pressed_when_it_says_download_pdf(presses, monkeypatch, tmp_path):
    month_select(monkeypatch)
    with pytest.raises(pressing.Stop):                                        # nothing downloads in this fake: the run stops, as the app says it must
        site.download_document(Page(El(text="Download PDF")), "U1234567", "Activity Statement", "t", "2026-09-30", tmp_path / "a.pdf", document_id_hint="202609")
    assert len(presses) == 1 and "2026" in presses[0]


@pytest.mark.parametrize("words", ["Update your statement delivery, contact support", "Download PDF and Trade", "Download", "PDF"])
def test_a_download_button_with_any_other_words_is_never_pressed(presses, monkeypatch, tmp_path, words):
    month_select(monkeypatch)
    assert site.download_document(Page(El(text=words)), "U1234567", "Activity Statement", "t", "2026-09-30", tmp_path / "a.pdf", document_id_hint="202609") is False
    assert presses == []


def test_a_month_that_cannot_be_read_presses_nothing(presses, monkeypatch, tmp_path):
    assert site.download_document(Page(El(text="Download PDF")), "U1234567", "Activity Statement", "t", "", tmp_path / "a.pdf", document_id_hint="") is False
    assert presses == []
