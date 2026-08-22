"""The guard that decides whether a control on the page may be touched.

These tests are the record of a real defect. Two shipped apps refused a
dropdown only when it belonged to a money-movement widget, so a control whose
identity said `login-form` read as ordinary and could be selected. It was
found on a third app, whose first probe missed every guessed URL, landed on
the provider's public site, and set a value inside a marketing page's login
dropdown.

Both directions are tested on purpose. A guard that is too tight is not safe,
it is broken in a quieter way, because refusing the year picker makes
discovery return nothing and an empty run looks like an empty account.
"""
import re

from paperpull_core import controls


SIGN_IN = [
    "whatDoYouWantToLogInto | login-form | Log in",
    "signin-form | Register | Create an account",
    "loginType | universalLogin | Sign On",
    "username | login | Password",
    "enrollment-form | Enroll now",
    "remember me | sign-up",
    "user_id | logon",
]

MONEY = [
    "fromAccount | transfer-form | Transfer money",
    "toAccount | Move money",
    "payee | billpay",
    "amount | send money",
    "frequency | schedule a payment",
    "recipient | zelle",
]

DOCUMENT_PICKERS = [
    "year | statement-year | Statements | Select year",
    "documentYear | Documents | View",
    "stmt-period | Statement period",
    "periodSelect | Choose a statement",
    "taxYear | Tax forms",
]


def test_sign_in_controls_are_refused():
    for identity in SIGN_IN:
        assert controls.is_forbidden_context(identity), identity


def test_money_controls_are_refused():
    for identity in MONEY:
        assert controls.is_forbidden_context(identity), identity


def test_document_pickers_are_allowed():
    """The other half of the promise. If these are refused, discovery silently
    finds nothing and the run looks like an account with no statements."""
    for identity in DOCUMENT_PICKERS:
        assert not controls.is_forbidden_context(identity), identity


def test_an_unreadable_identity_fails_closed():
    assert controls.is_forbidden_context("")
    assert controls.is_forbidden_context(None or "")


def test_the_app_can_add_its_own_vocabulary():
    """A provider passes its own forbidden pattern. Chase's rewards vocabulary
    means nothing to Ally, and neither belongs in the shared rules."""
    chase_ish = re.compile(r"cashback|rewards|redeem", re.I)
    assert controls.is_forbidden_context("redeem | rewards-widget", chase_ish)
    assert not controls.is_forbidden_context("redeem | rewards-widget")


def test_options_are_checked_against_the_extra_patterns():
    """Some pickers only reveal what they are through what they offer."""
    products = re.compile(r"student\s+loan|bank\s+account", re.I)
    assert controls.is_forbidden_context(
        "select-2 | chooser", extra_res=[products],
        options=["Credit card", "Student loan"])
    assert not controls.is_forbidden_context(
        "select-2 | chooser", extra_res=[products],
        options=["January 2026", "February 2026"])


def test_no_pattern_contains_a_control_character():
    """A backslash-b written through a shell heredoc becomes a literal
    backspace, and the pattern then matches nothing while still compiling.
    That has happened twice in this repo."""
    for rx in (controls.MONEY_CONTROL_RE, controls.AUTH_CONTROL_RE):
        assert "\b" not in rx.pattern, rx.pattern
        assert "\\b" in rx.pattern or "\\s" in rx.pattern


class _FakeLocator:
    def __init__(self, value=None, raises=False):
        self._value, self._raises = value, raises

    def evaluate(self, _js):
        if self._raises:
            raise RuntimeError("detached")
        return self._value


def test_identity_of_a_detached_element_is_empty_and_therefore_unsafe():
    assert controls.control_identity(_FakeLocator(raises=True)) == ""
    assert controls.is_forbidden_context(
        controls.control_identity(_FakeLocator(raises=True)))


def test_identity_passes_through_what_the_page_reports():
    loc = _FakeLocator("year | Statements")
    assert controls.control_identity(loc) == "year | Statements"


class _FakeSelects:
    """The smallest thing describe_selects will walk."""
    def __init__(self, identities):
        self._ids = identities

    def locator(self, _sel):
        return self

    def count(self):
        return len(self._ids)

    def nth(self, i):
        return _FakeLocator(self._ids[i])


def test_describe_selects_key_names_are_a_contract():
    """Apps read these keys BY NAME out of the diagnose report.

    When the guard moved into the core the verdict key was renamed from
    `refused_as_money_control` to `refused`, and the Ally and Chase diagnose
    summaries kept filtering on the old one. Nothing failed. The line that
    reports refused dropdowns simply stopped appearing, which is the one
    output that would reveal a document picker refused by mistake.

    So the names are pinned here. Renaming one should fail this test and send
    whoever did it to look at the callers.
    """
    rows = controls.describe_selects(
        _FakeSelects(["fromAccount | transfer-form", "year | Statements"]))
    assert len(rows) == 2
    for row in rows:
        assert set(row) == {"identity", "refused"}, sorted(row)
    assert rows[0]["refused"] is True
    assert rows[1]["refused"] is False
