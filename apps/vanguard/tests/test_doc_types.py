"""Synthetic fixtures for provider parsing, filing and control checks.

Vanguard truth: the statements app serves monthly/quarterly account
statements via personal1.vanguard.com's lah-statements-consumer API
(captured live 2026-09-28); classify_document maps a captured statement
dict to the engine's (category, date, period, title)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage
from paperpull_core import doc_types
import vanguard_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


def _stmt(**kw):
    """A captured statement dict in the API's real shape (field names and
    values from the live capture)."""
    base = {
        "accountId": "123400000000001",
        "accountNumber": "1234567",
        "productAccountData": "1234567|VBS",
        "statementDescription": "Example Holder \u2014 Cash Plus Account \u2014 1234567",
        "endDate": "2026-02-28",
        "processDate": "2026-02-28",
        "frequencyType": "QUARTERLY",
        "statementType": "ACCOUNT_GROUP",
        "statementId": "opaque==",
        "statementNumber": "675000001",
    }
    base.update(kw)
    return base


def test_a_brokerage_statement_files_on_its_own_date():
    cat, date, period, title = site.classify_document(_stmt())
    assert cat == "Statement"
    assert date == "2026-02-28"
    assert period == "2026-02"
    assert title == "Account Statement - Example Holder \u2014 Cash Plus Account \u2014 1234567"


def test_a_monthly_statement_is_also_a_statement():
    cat, date, _p, _t = site.classify_document(
        _stmt(frequencyType="MONTHLY", endDate="2026-08-31"))
    assert cat == "Statement"
    assert date == "2026-08-31"


def test_process_date_is_the_fallback_when_end_date_is_missing():
    cat, date, _p, _t = site.classify_document(
        _stmt(endDate="", processDate="2026-09-02"))
    assert date == "2026-09-02"


def test_the_accounts_label_comes_from_the_statement_description():
    label = site.account_label_from_statement(_stmt())
    assert label == "Example Holder \u2014 Cash Plus Account \u2014 1234567"


def test_the_label_falls_back_to_the_account_number():
    label = site.account_label_from_statement(_stmt(statementDescription=""))
    assert label == "Vanguard Account 1234567"


def test_account_display_maps_back_to_the_account_id():
    assert site.account_id_from_display(
        "Example Holder \u2014 Cash Plus Account \u2014 1234567") == "1234567"


def test_filename():
    storage.set_filename_owner("")
    assert build_pdf_filename(
        "2026-08-31",
        "Account Statement - Example Holder \u2014 Cash Plus Account \u2014 1234567",
        "") == \
        "2026-08-31 Vanguard Account Statement - Example Holder \u2014 Cash Plus Account" \
        " \u2014 1234567.pdf"


def test_api_dates_round_trip_through_the_row_format():
    # The API says 2026-08-31; the table row prints 08/31/2026.
    assert site.parse_date("2026-08-31") == "2026-08-31"
    assert site.parse_date("08/31/2026") == "2026-08-31"
    assert site._mdy("2026-08-31") == "08/31/2026"


def test_documents_page_detection_is_structural_not_row_based():
    # The Chase empty-year lesson: page presence must never depend on
    # rendered rows. A stub page on the statements host WITH a table counts.
    class _L:
        def count(self):
            return 1

    class _P:
        url = "https://statements.web.vanguard.com/"

        def locator(self, _s):
            return _L()

    assert site.on_documents_page(_P())


def test_signed_out_reads_the_vanguard_logon_host():
    class _L:
        def count(self):
            return 0

    class _P:
        url = "https://investor.vanguard.com/myaccount/documents"

        def locator(self, _s):
            return _L()

    class _Q(_P):
        url = "https://logon.vanguard.com/logon?site=pi"

    assert not site.looks_signed_out(_P())
    assert site.looks_signed_out(_Q())


# --------------------------------------------------------------- guards

def test_trading_actions_are_never_safe():
    for label in ["Buy", "Sell shares", "Place order", "Preview order",
                  "Exchange funds", "Rebalance portfolio",
                  "Trade now", "Exercise option"]:
        assert not site.is_safe_control(label), label


def test_money_actions_are_never_safe():
    for label in ["Move money", "Withdraw funds", "Transfer assets",
                  "Deposit check", "Wire money", "ACH transfer",
                  "Contribution", "Distribution request"]:
        assert not site.is_safe_control(label), label


def test_settings_actions_are_never_safe():
    for label in ["Profile settings", "Change password",
                  "Update contact information", "Beneficiaries",
                  "Paperless settings"]:
        assert not site.is_safe_control(label), label


def test_document_actions_are_safe():
    for label in ["Pdf download icon", "View PDF",
                  "Download a pdf statement generated on August 31, 2026",
                  "Statements", "Tax Forms", "Historical documents",
                  "Confirmations"]:
        assert site.is_safe_control(label), label


def test_trade_confirms_chip_is_safe_but_trade_is_not():
    # "Confirmations" (the documents area) is safe; "Trade" alone is not.
    assert site.is_safe_control("Confirmations")
    assert not site.is_safe_control("Trade")


def test_the_real_statement_picker_is_allowed():
    # The year and account selects on the statements page.
    assert site.is_safe_control("select year")
    assert site.is_safe_control("select account")


def test_a_verb_stem_inside_another_word_is_not_a_refusal():
    # "statement" contains no stem of "trade"/"sell"/"buy"; "Credit" must
    # not trip the change/edit/update stems; the Schwab lesson.
    assert site.is_safe_control("Download a Credit Card Statement")
    assert not site.is_safe_control("Edit profile")


def test_empty_or_ambiguous_control_not_safe():
    assert not site.is_safe_control("")
    assert not site.is_safe_control("   ")
    assert not site.is_safe_control("click here")


def test_only_vanguard_hosts_are_safe_urls():
    assert site.is_safe_url("https://statements.web.vanguard.com/")
    assert site.is_safe_url("https://investor.vanguard.com/myaccount/documents")
    assert site.is_safe_url("https://personal1.vanguard.com/usa/api/anything")
    assert not site.is_safe_url("https://statements.web.vanguard.com.example.org/")
    assert not site.is_safe_url("https://evil.example/")
    assert not site.is_safe_url("file:///etc/passwd")


def test_statements_are_in_scope_by_default():
    cfg = {"document_types": storage.ALL_CATEGORIES}
    for cat in ["Statement", "Tax Document", "Letter", "Trade Confirmation",
                "Report"]:
        assert doc_types.wanted(cat, cfg), cat
    assert not doc_types.wanted("Other Document", cfg)


def test_money_control_identity_check():
    assert site.is_money_control("Buy button")
    assert site.is_money_control("Withdraw")
    assert not site.is_money_control("Pdf download icon")
    # Empty identity is treated as money (fail closed).
    assert site.is_money_control("")

def test_an_update_with_contact_later_in_the_label_is_still_refused():
    # The 2026-09-28 external review's bypass: an unbounded lookahead
    # exempted any "update" if "contact" appeared anywhere later in the
    # label. The update/edit clauses carry no exceptions now.
    assert not site.is_safe_control(
        "Update your statement delivery, contact support if issues")


def test_logon_is_an_auth_control():
    # Vanguard's own sign-in domain is logon.vanguard.com; the core AUTH
    # pattern (imported, not local) must recognize it.
    assert site.AUTH_CONTROL_RE.search("Logon")
    assert site.is_money_control("Logon to your account")


class _FakeIcon:
    def __init__(self, label):
        self._label = label
        self.clicked = 0

    def get_attribute(self, name):
        if name == "aria-label":
            return self._label
        return None

    def click(self, **kw):
        self.clicked += 1
        raise AssertionError("click reached on a guarded-refusal path")


class _FakeTitleLocator:
    def __init__(self, icon):
        self._icon = icon

    @property
    def first(self):
        return self._icon


class _FakeRow:
    def __init__(self, icon):
        self._icon = icon

    def get_by_title(self, _title):
        return _FakeTitleLocator(self._icon)


class _FakeRowChain:
    def __init__(self, icon):
        self._icon = icon

    def filter(self, **kw):
        return self

    @property
    def first(self):
        return _FakeRow(self._icon)


class _FakeLocator:
    def __init__(self, icon):
        self._icon = icon

    def count(self):
        return 1            # the statements table exists (on_documents_page)

    def filter(self, **kw):
        return _FakeRowChain(self._icon)


class _FakePage:
    """Exactly the surface download_document touches before the click."""

    def __init__(self, icon_label, row_exists=True):
        self.url = "https://statements.web.vanguard.com/"
        self._icon = _FakeIcon(icon_label)
        self.row_exists = row_exists
        self.eval_calls = 0

    def locator(self, sel):
        return _FakeLocator(self._icon)

    def evaluate(self, js, arg=None):
        self.eval_calls += 1
        return self.row_exists

    def wait_for_timeout(self, ms):
        pass

    def expect_download(self, timeout=None):
        """Runs the click body, then reports the timeout a fake page must
        report — the click itself is what the wiring tests measure, and it
        happens inside the with-block."""
        class _NoEvent:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                # the click ran inside the block; the download never comes
                raise RuntimeError("no download event on a fake page")

        return _NoEvent()


@pytest.fixture()
def pressed_as_given(monkeypatch):
    """pressing.click reads what is on top of a control in a real page, and
    these pages are fakes, so the press is handed straight to the fake
    icon. It is bound to the real function's signature first, so a keyword
    the real one would refuse fails here too."""
    import inspect
    from paperpull_core import pressing
    real = inspect.signature(pressing.click)

    def stand_in(*args, **kwargs):
        real.bind(*args, **kwargs).arguments["locator"].click()

    monkeypatch.setattr(pressing, "click", stand_in)


def test_an_unsafe_label_never_reaches_the_click(tmp_path, monkeypatch, pressed_as_given):
    """The wiring, not the function: download_document() with an unsafe
    icon label must return False with the icon never clicked. If the
    guard call is deleted from download_document again, THIS test fails
    (the round-2 review's mutation finding)."""
    page = _FakePage("Buy this security now")
    out = tmp_path / "x.pdf"
    got = site.download_document(
        page, account_id="internal", charitable=False, doc_type="Statement",
        title="Account Statement - Example Holder \u2014 Cash Plus Account \u2014 1234567",
        date="2026-08-31", out_path=out)
    assert got is False
    assert page._icon.clicked == 0, "guard refused but the icon was clicked"
    assert not out.exists()


def test_a_safe_nbsp_label_reaches_the_click(tmp_path, monkeypatch, pressed_as_given):
    """The same wiring with the real label shape (unfolded NBSPs) must
    get as far as the click attempt; the fake icon records the attempt
    and the download event then fails closed (no event on a fake page),
    so False comes back WITH the click attempted — proving the guard
    did not over-refuse the app's own control."""
    label = ("Download\u00a0a\u00a0pdf\u00a0statement generated on "
             "August 31, 2026 with description Example Holder \u2014 "
             "Cash Plus Account \u2014 1234567")

    class _ClickRecorder(_FakeIcon):
        def click(self, **kw):
            self.clicked += 1
            raise RuntimeError("no download event on a fake page")

    page = _FakePage(label)
    page._icon.__class__ = _ClickRecorder
    out = tmp_path / "y.pdf"
    got = site.download_document(
        page, account_id="internal", charitable=False, doc_type="Statement",
        title="Account Statement - Example Holder \u2014 Cash Plus Account \u2014 1234567",
        date="2026-08-31", out_path=out)
    assert got is False            # the capture fails (no real browser)
    assert page._icon.clicked == 1, "guard over-refused the real label"
    assert not out.exists()        # and nothing was left behind
