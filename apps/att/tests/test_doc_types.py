"""AT&T classification, the carrier guard, and the survey's promises.

The site layer is unverified, so what these pin is everything that must be
true before a tester ever runs it: the guard refuses every control that
pays or changes service, the survey cannot leak a number, and a bill row's
date is read in the forms att.com is likely to print it in.
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds AT&T's AppSpec
from paperpull_core import doc_types
import att_site as site
from storage import build_pdf_filename

RULES = doc_types.load_rules()


# -- classification -------------------------------------------------------

def test_bills_are_monthly_statements():
    for title in ["Monthly Statement - August 12, 2026", "Wireless bill", "Bill",
                  "Fiber bill", "Invoice", "Monthly bill for July"]:
        cat, s, _ = doc_types.classify_document(title, RULES)
        assert cat == doc_types.STATEMENT, title
        assert s == "Monthly Statement", (title, s)


def test_payment_receipts_and_marketing_are_skipped():
    for t in ["Payment receipt", "Payment confirmation", "AutoPay enrollment",
              "Paperless billing", "Customer Agreement", "Usage details", "Offers for you"]:
        assert doc_types.should_skip(t, RULES), t
    assert not doc_types.should_skip("Monthly Statement - August 12, 2026", RULES)


def test_filename_shape():
    storage.set_filename_owner("")
    assert build_pdf_filename("2026-08-12", "Monthly Statement", "") == \
        "2026-08-12 AT&T Monthly Statement.pdf"


# -- the carrier guard ------------------------------------------------------

def test_every_control_that_pays_or_changes_service_is_refused():
    for label in ["Pay now", "Make a payment", "Set up AutoPay", "Manage AutoPay",
                  "Payment arrangement", "Add a line", "Upgrade", "Trade in your phone",
                  "Change plan", "Shop plans", "Add-ons", "Buy now", "Cart", "Checkout",
                  "Suspend service", "Restore service", "Transfer your number",
                  "Get a new SIM", "Activate eSIM", "International roaming",
                  "Cancel service", "Go paperless", "Update profile", "Change password",
                  "Chat with us", "Contact us", "Submit", "Confirm", "Save Changes",
                  "Turn off", "Manage", "Edit address", "Deals", "Move"]:
        assert not site.is_safe_control(label), label


def test_the_controls_that_fetch_a_bill_are_allowed():
    for label in ["Download bill", "Download bill (PDF)", "View bill", "Print bill",
                  "See bill", "Bill PDF", "PDF", "View bill history", "See more bills",
                  "Show older bills", "Download statement"]:
        assert site.is_safe_control(label), label
        assert site.BILL_CONTROL_RE.search(label) or "more" in label or "older" in label \
            or "history" in label, label


def test_a_bill_control_that_also_pays_is_refused():
    """"View and pay bill" is one control on some carrier pages. The pay
    word wins, whatever else the label says."""
    for label in ["View and pay bill", "Pay bill", "Download bill and pay",
                  "View bill / Make a payment"]:
        assert not site.is_safe_control(label), label


def test_the_login_and_settings_vocabulary_is_refused_too():
    for label in ["Sign in", "Log in", "Remember me", "Preferences", "Settings"]:
        assert not site.is_safe_control(label), label


# -- dates, the identity of a bill -------------------------------------------

def test_bill_dates_in_every_form_att_prints():
    assert site.parse_date("Aug 12, 2026 Download bill PDF") == "2026-08-12"
    assert site.parse_date("August 12, 2026") == "2026-08-12"
    assert site.parse_date("Bill for 08/12/2026") == "2026-08-12"
    assert site.parse_date("08/12/26") == "2026-08-12"
    assert site.parse_date("2026-08-12") == "2026-08-12"
    assert site.parse_date("no date here") is None
    assert site.parse_period_date("August 2026") == ("2026-08-31", "August 2026")
    assert site._human_date("2026-08-12") == "August 12, 2026"


# -- the survey a tester attaches to an issue --------------------------------

def test_the_survey_masks_numbers_and_takes_no_screenshot():
    assert site.redact("account 123456789 bill") == "account ######### bill"
    assert site.redact("Aug 12, 2026") == "Aug 12, 2026"       # dates are short runs
    assert site.redact("phone 555-0100") == "phone 555-0100"
    for fn in (site.survey, site._page_summary, site.collect_documents):
        assert ".screenshot(" not in inspect.getsource(fn)
    docs_src = (Path(site.__file__).parent / "att_docs.py").read_text(encoding="utf-8")
    assert ".screenshot(" not in docs_src
    assert site._shape({"bills": [{"amount": 12.5, "date": "x"}], "n": 3}) == \
        {"bills": ["1 item(s)", {"amount": "number", "date": "string"}], "n": "number"}


def test_the_survey_follows_only_billing_links():
    for text in ["Bill history", "See bill history", "View bills", "Past bills",
                 "Billing", "Statements"]:
        assert site.SURVEY_LINK_RE.match(text), text
    for text in ["Pay bill", "Upgrade", "Shop", "Account", "Support"]:
        assert not site.SURVEY_LINK_RE.match(text), text


# -- hosts --------------------------------------------------------------------

def test_only_att_hosts():
    assert site.is_safe_url("https://www.att.com/acctmgmt/billandpay/history")
    assert site.is_safe_url("https://signin.att.com/x")
    assert not site.is_safe_url("https://att.com.evil.test/bill.pdf")
    assert not site.is_safe_url("http://www.att.com/bill.pdf")
    assert not site.is_safe_url("https://user@att.com/bill.pdf")
    assert all(site.is_safe_url(u) for u in site.BILLING_CANDIDATES)


def test_the_status_is_stated_where_a_tester_will_read_it():
    src = Path(site.__file__).read_text(encoding="utf-8")
    assert "STATUS: round nine" in src.split('"""')[1]
    readme = (Path(site.__file__).parent / "README.md").read_text(encoding="utf-8")
    assert "still being finished" in readme and "Not yet tested" not in readme


# -- round two, from the first tester's survey (#26) --------------------------

class _Loc:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n

    def or_(self, other):
        return _Loc(self._n + other._n)


class _Page:
    def __init__(self, url, bill_controls=1, body=""):
        self.url = url
        self._n = bill_controls
        self._body = body

    def get_by_role(self, role, name=None):
        # the fake splits its bill controls between the two roles
        return _Loc(self._n - self._n // 2 if role == "button" else self._n // 2)

    def locator(self, sel):
        page = self

        class _Body:
            def inner_text(self_, timeout=0):
                return page._body
        return _Body()


def test_the_overview_with_its_one_view_bill_button_is_not_the_billing_page():
    """Sign-in lands on /acctmgmt/overview, a shop page with one "View
    bill" button. That button alone passed the first check, so discovery
    read 125 rows of phones and cases and no bills."""
    assert not site._looks_like_billing(_Page("https://www.att.com/acctmgmt/overview?x=1", bill_controls=1))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/billing/mybillingcenter", bill_controls=0))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/x", bill_controls=3))
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/x", bill_controls=0, body="Your bill history"))


def test_the_billing_center_is_tried_first_and_the_nav_link_is_allowed():
    assert site.BILLING_CANDIDATES[0] == "https://www.att.com/acctmgmt/billing/mybillingcenter"
    assert site.is_safe_control("Billing")
    assert site.BILLING_NAV_RE.match("Billing") and site.BILLING_NAV_RE.match("Bill & payments")
    for text in ("Billing", "View bill", "Bill history"):
        assert site.SURVEY_LINK_RE.match(text), text
    # The nav's money words stay refused whatever the survey wants.
    for text in ("Payments", "Pay off my device", "Check my usage", "See usage details"):
        assert not site.is_safe_control(text), text


def test_a_url_in_the_survey_loses_its_query_string():
    """Query strings carry session details the survey has no use for.
    Nothing after the ? reaches the file."""
    assert site.redact("https://www.att.com/acctmgmt/overview?haloSuccess=true&lt=abcDEF123456789") == \
        "https://www.att.com/acctmgmt/overview?..."
    assert site.redact("see https://www.att.com/a?b=c and https://www.att.com/d") == \
        "see https://www.att.com/a?... and https://www.att.com/d"


# -- round three, from the second survey ------------------------------------

def test_the_history_api_answer_gives_every_bill_its_date_and_hint():
    """content.historyList[] of {type, displayDate, cycleStartDate,
    cycleEndDate, statementId, invoiceIndex, ...}, the shape the second
    survey recorded. Payments are left out, the id rides as the hint."""
    body = {"content": {"accountNumber": "x", "billFound": True, "historyList": [
        {"type": "Bill", "displayDate": "Aug 22, 2026", "cycleStartDate": "07/23/2026",
         "cycleEndDate": "08/22/2026", "statementId": "S1", "invoiceIndex": "3"},
        {"type": "Payment", "displayDate": "Aug 10, 2026", "cycleEndDate": "", "statementId": ""},
        {"type": "Bill", "displayDate": "Jul 22, 2026", "cycleStartDate": "2026-06-23",
         "cycleEndDate": "2026-07-22", "statementId": "S2", "invoiceIndex": "2"},
        {"type": "Bill", "displayDate": "Jun 22, 2026", "statementId": "S3"},
    ]}}
    got = site._history_from_api(body)
    assert [(b["date"], b["hint"], b["start"]) for b in got] == [
        ("2026-08-22", "S1|3", "2026-07-23"), ("2026-07-22", "S2|2", "2026-06-23"), ("2026-06-22", "S3|", "")]
    assert site._history_from_api({}) == [] and site._history_from_api({"content": {}}) == []


def test_bill_buttons_without_a_year_step_the_year_back_across_january():
    """"Bill / Jul 23 - Aug 22 / $xx.xx". The newest takes this year, and
    each older one goes back a year whenever its month is later than the
    one before it."""
    iso, prev = site._period_end("Bill\nJan 23 - Feb 22\n$10.00", 2026, None)
    assert (iso, prev) == ("2026-02-22", 2)
    iso, prev = site._period_end("Bill\nDec 23 - Jan 22\n$10.00", 2026, 2)
    assert (iso, prev) == ("2026-01-22", 1)
    iso, prev = site._period_end("Bill\nNov 23 - Dec 22\n$10.00", 2026, 1)
    assert (iso, prev) == ("2025-12-22", 12)
    assert site._period_end("Bill\nno dates here", 2026, 12) == (None, 12)


def test_the_two_pdf_buttons_are_allowed_and_see_bill_history_is_not_a_bill():
    for text in ("Download PDF", "View/print PDF"):
        assert site.PDF_BUTTON_RE.match(text), text
        assert site.is_safe_control(text), text
    assert not site.PDF_BUTTON_RE.match("Download bill & payment info")
    # Round two clicked this instead of Download PDF. It is navigation.
    assert not site.BILL_CONTROL_RE.search("See bill history")
    assert site.BILL_CONTROL_RE.search("View bill") and site.BILL_CONTROL_RE.search("Download PDF")
    # The history page's bill buttons pass the guard, the account picker does not matter.
    assert site.is_safe_control("Bill\nJul 23 - Aug 22\n$xx.xx")
    assert site.BILL_BUTTON_RE.match("Bill\nJul 23 - Aug 22\n$xx.xx")


def test_the_history_page_counts_as_billing_and_its_api_is_recognized():
    assert site._looks_like_billing(_Page("https://www.att.com/acctmgmt/billing/billandpaymenthistory?filter=bill", bill_controls=0))
    assert site.HISTORY_API_RE.search("https://www.att.com/msapi/webbillexpms/v1/billandpaymenthistory")
    assert not site.HISTORY_API_RE.search("https://www.att.com/msapi/webbillexpms/v1/billandpaymenthistorygraph")
    assert site.HISTORY_URL.startswith("https://www.att.com/acctmgmt/billing/billandpaymenthistory")


def test_download_bill_takes_a_hint_and_a_trace():
    params = inspect.signature(site.download_bill).parameters
    assert "hint" in params and "trace" in params


# -- round four, from the round-three pilot ------------------------------------

class _Btn:
    def __init__(self, text, label=""):
        self._text, self._label = text, label
    def inner_text(self, timeout=0): return self._text
    def get_attribute(self, name): return self._label if name == "aria-label" else None
    def is_visible(self): return True
    def scroll_into_view_if_needed(self, timeout=0): pass


class _TextLoc:
    def __init__(self, items): self._items = items
    def count(self): return len(self._items)
    def nth(self, i): return self._items[i]
    def filter(self, has_text=None):
        return _TextLoc([b for b in self._items if has_text.search(b._text)])


class _HistoryPage:
    """Buttons whose accessible name says nothing about the period."""
    url = "https://www.att.com/acctmgmt/billing/billandpaymenthistory?filter=bill"
    def __init__(self):
        self.buttons = [_Btn("Account\n123456789\nWireless", "Switch account"),
                        _Btn("Bill\nJul 23 - Aug 22\n$88.05", "View details"),
                        _Btn("Bill\nJun 23 - Jul 22\n$88.05", "View details")]
    def get_by_role(self, role, name=None):
        assert name is None, "round three matched on the accessible name and found nothing"
        return _TextLoc(self.buttons if role == "button" else [])


def test_the_bill_button_is_matched_on_its_visible_text_not_its_name():
    page = _HistoryPage()
    el, text = site._bill_button_for(page, "2026-08-22")
    assert el is page.buttons[1] and text.startswith("Bill")
    el, _ = site._bill_button_for(page, "2026-07-22")
    assert el is page.buttons[2]
    assert site._bill_button_for(page, "2026-09-11") == (None, "")
    assert site._period_buttons(page).count() == 2


def test_a_miss_records_the_buttons_it_saw_with_digits_masked():
    seen = site._buttons_seen(_HistoryPage())
    assert seen[0] == "Account / ######### / Wireless"
    assert "Bill / Jul 23 - Aug 22 / $x.xx" in seen, "amounts are masked too now"


def test_the_billing_center_fallback_opens_the_billing_center_itself():
    src = inspect.getsource(site.download_bill)
    assert "page.goto(BILLING_CANDIDATES[0]" in src
    assert "goto_documents(page)" not in src.split("# The current bill")[1]


# -- round five, from the round-four trace ------------------------------------

def test_a_pdf_the_browser_saved_itself_is_taken_from_the_download_folder(tmp_path):
    """A real Edge or Chrome attached over CDP saves a download itself and
    Playwright never sees it. Round four's trace showed a clean click on
    Download PDF and nothing arriving."""
    dl = tmp_path / "dl"; dl.mkdir()
    (dl / "old.pdf").write_bytes(b"%PDF-old")
    before = site._snapshot(dl)
    out = tmp_path / "out.pdf"
    assert not site._take_new_pdf(dl, before, out)
    (dl / "bill.pdf.crdownload").write_bytes(b"%PDF-")
    assert not site._take_new_pdf(dl, before, out), "a file still downloading is not finished"
    (dl / "notes.txt").write_bytes(b"hello")
    assert not site._take_new_pdf(dl, before, out), "only a PDF counts"
    (dl / "bill.pdf").write_bytes(b"%PDF-1.7 the bill")
    assert site._take_new_pdf(dl, before, out)
    assert out.read_bytes() == b"%PDF-1.7 the bill" and not (dl / "bill.pdf").exists()
    assert (dl / "old.pdf").exists()
    assert site._take_new_pdf(None, set(), out) is False


def test_the_orchestrator_points_the_browser_at_a_folder_it_watches():
    docs_src = (Path(site.__file__).parent / "att_docs.py").read_text(encoding="utf-8")
    assert "site.set_download_dir(self._work_page, self._dl_dir)" in docs_src
    assert "_dl_dir = None" not in docs_src
    assert "dl_dir" in inspect.signature(site._catch_pdf).parameters


def test_a_pdf_in_a_new_tab_is_read_only_from_a_blob_or_an_att_host(tmp_path):
    class _Tab:
        def __init__(self, url, b64): self.url, self._b64 = url, b64
        def wait_for_load_state(self, *_ , **__): pass
        def evaluate(self, js, url): return self._b64
    class _Page:
        def evaluate(self, js, url): return "JVBERi0xLjcgYmxvYg=="   # %PDF-1.7 blob
    out = tmp_path / "t.pdf"
    assert not site._take_new_tab(_Page(), [_Tab("https://evil.test/x.pdf", "JVBERi0xLjc=")], out)
    assert site._take_new_tab(_Page(), [_Tab("https://www.att.com/x.pdf", "JVBERi0xLjcgYXR0")], out)
    assert out.read_bytes().startswith(b"%PDF-1.7")
    assert site._take_new_tab(_Page(), [_Tab("blob:https://www.att.com/abc", None)], out)
    assert out.read_bytes() == b"%PDF-1.7 blob"


# -- round six, from the round-five trace ------------------------------------

class _Ctl:
    def __init__(self, text, visible=True): self._text, self._visible = text, visible
    def inner_text(self, timeout=0): return self._text
    def get_attribute(self, name): return None
    def is_visible(self): return self._visible
    def click(self, timeout=0): self.clicked = True


class _RoleLoc:
    def __init__(self, items): self._items = items
    def count(self): return len(self._items)
    def nth(self, i): return self._items[i]
    @property
    def first(self): return self._items[0]


class _AfterClick:
    """A page whose Download PDF click opened a small menu."""
    url = "https://www.att.com/acctmgmt/billing/billandpaymenthistory"
    def __init__(self, texts): self.texts = texts
    def get_by_role(self, role, name=None):
        items = [_Ctl(t) for t in self.texts if role == "button" and (name is None or name.match(t))]
        return _RoleLoc(items)
    def evaluate(self, js): return ["blob:https://www.att.com/abc"] if "iframe" in js else None


def test_the_control_the_click_revealed_is_the_second_step_and_pay_never_is():
    before = site._control_texts(_AfterClick(["Download PDF", "See bill history"]))
    after = site._control_texts(_AfterClick(["Download PDF", "See bill history", "Full bill", "Pay now", "Cancel"]))
    appeared = after - before
    assert appeared == {"Full bill", "Pay now", "Cancel"}
    step, label = site._second_step(_AfterClick(sorted(appeared)), appeared)
    assert label == "Full bill"
    assert site._second_step(_AfterClick(["Pay now", "Cancel"]), {"Pay now", "Cancel"}) == (None, "")
    for t in ("Download", "Save as PDF", "Bill PDF", "View/print PDF"):
        assert site._SECOND_STEP_RE.match(t) and site.is_safe_control(t), t
    for t in ("Pay now", "Make a payment", "Cancel", "Enroll in AutoPay"):
        assert not site.is_safe_control(t), t


def test_an_embedded_viewer_is_read_through_the_page(tmp_path):
    class _P(_AfterClick):
        def evaluate(self, js, *a):
            if "iframe" in js:
                return ["blob:https://www.att.com/abc"]
            return "JVBERi0xLjcgdmlld2Vy"   # %PDF-1.7 viewer
    out = tmp_path / "v.pdf"
    trace = []
    assert site._take_viewer(_P([]), out, trace)
    assert out.read_bytes().startswith(b"%PDF-1.7")
    assert trace[0]["note"] == "embedded viewers after the click"


def test_the_click_outcome_is_in_the_trace():
    src = inspect.getsource(site._catch_pdf)
    for note in ('"clicked"', '"click failed"', '"after the click"', '"second step clicked"'):
        assert note in src, note
    assert "expect_download" not in src, "a swallowed expect_download hid whether the click landed"


# -- round eight, the menu's entries are found by text (#26) ------------------

class _TextEl:
    def __init__(self, text, visible=True):
        self._t = text
        self._v = visible

    def inner_text(self, timeout=0):
        return self._t

    def is_visible(self):
        return self._v


class _MenuLoc:
    def __init__(self, els):
        self._els = els

    def count(self):
        return len(self._els)

    def nth(self, i):
        return self._els[i]


class _MenuPage:
    """A page whose "Download PDF" menu is made of plain elements, the way
    round seven's trace showed it, with the entries hidden until the menu
    opens a moment later."""
    def __init__(self, open_after=1):
        self._open_after = open_after
        self.waited = 0

    def get_by_text(self, pat):
        visible = self.waited >= self._open_after
        els = [_TextEl(t, visible) for t in ("Regular PDF", "View/print PDF", "Accessibility PDF")
               if pat.match(t)]
        return _MenuLoc(els)

    def wait_for_timeout(self, ms):
        self.waited += 1


def test_the_regular_pdf_entry_is_found_by_text_once_the_menu_opens():
    page = _MenuPage(open_after=2)
    el, label = site._menu_entry(page, site._REGULAR_PDF_RE, wait_ms=3000)
    assert el is not None and label == "Regular PDF"
    assert page.waited == 2
    el, label = site._menu_entry(_MenuPage(open_after=99), site._REGULAR_PDF_RE, wait_ms=1000)
    assert el is None and label == ""


def test_the_menu_entries_pass_the_guard_and_the_accessibility_one_is_not_preferred():
    assert site.is_safe_control("Regular PDF")
    assert site.is_safe_control("View/print PDF")
    assert site._REGULAR_PDF_RE.match("Regular PDF") and not site._REGULAR_PDF_RE.match("Accessibility PDF")
    assert site._VIEW_PRINT_RE.match("View/print PDF") and site._VIEW_PRINT_RE.match("View / print PDF")


# -- round nine, the account's kind and the due date (#26) --------------------

class _SwitcherPage:
    def __init__(self, text):
        self._t = text

    def get_by_role(self, role, name=None):
        page = self

        class _L:
            def count(self_): return 1
            def nth(self_, i): return self_
            def inner_text(self_, timeout=0): return page._t
        return _L()


def test_the_accounts_kind_is_read_off_the_switcher_and_leads_nowhere_else():
    assert site.current_account_label(_SwitcherPage("Account\n123456789\nWireless")) == "Wireless"
    assert site.current_account_label(_SwitcherPage("Account\n123456789\nFiber")) == "Fiber"
    assert site.current_account_label(_SwitcherPage("Account\n123456789\nInternet")) == "Internet"
    assert site.current_account_label(_SwitcherPage("Account\n123456789\nMobility")) == "Wireless"
    assert site.current_account_label(_SwitcherPage("Account\n123456789")) == ""


# -- round ten, two accounts in the switcher (#26) ----------------------------

class _NoSwitcherPage:
    """A page whose switcher is not a button named "Account", which is
    what the fiber account turned out to have."""

    def __init__(self, found):
        self._found = found

    def get_by_role(self, role, name=None):
        class _L:
            def count(self_): return 0
            def nth(self_, i): return self_
            def inner_text(self_, timeout=0): return ""
        return _L()

    def evaluate(self, js, *a):
        return self._found


def test_the_account_in_focus_is_the_first_one_the_switcher_lists():
    """His note is that the order changes, with the account he is on
    listed first. Round nine read the lines backwards and so named the
    other account."""
    both = "Account\n123456789\nFiber\nAccount\n987654321\nWireless"
    assert site.current_account_label(_SwitcherPage(both)) == "Fiber"
    flipped = "Account\n987654321\nWireless\nAccount\n123456789\nFiber"
    assert site.current_account_label(_SwitcherPage(flipped)) == "Wireless"


def test_a_switcher_that_is_not_a_button_named_account_is_still_read():
    page = _NoSwitcherPage([{"text": "Account 123456789 Internet", "tag": "div",
                             "label": "", "selected": True, "top": 10, "left": 0}])
    assert site.current_account_label(page) == "Internet"
    assert site.current_account_label(_NoSwitcherPage([])) == ""
    # and the survey can show what it was deciding from
    assert site.switcher_candidates(_NoSwitcherPage([{"text": "x"}])) == [{"text": "x"}]


def test_the_switcher_reader_asks_the_page_and_presses_nothing():
    js = site._SWITCHER_JS
    assert ".click(" not in js and "submit" not in js, "the survey presses nothing"
    assert "aria-selected" in js and "getBoundingClientRect" in js


def test_a_due_date_is_never_a_bill_date():
    assert site._date_not_due("Bill issued Sep 11, 2026") == "2026-09-11"
    assert site._date_not_due("Current balance $88.05\nDue Sep 30, 2026") is None
    assert site._date_not_due("Amount due Sep 30, 2026\nBill date Sep 11, 2026") == "2026-09-11"
    assert site._date_not_due("no date") is None


def test_a_bill_discovered_before_the_label_existed_takes_the_new_name():
    """Ten rounds in, the reading was right and the filename was still
    bare, because his fiber bills were found in an earlier round and a
    refresh only ever updated where the link lived (#26)."""
    src = (Path(site.__file__).parent / "att_docs.py").read_text(encoding="utf-8")
    block = src.split("# refresh which page the doc's download link lives on")[1][:1200]
    assert 'patch["summary"] = summary' in block
    assert "downloaded_ok" in block, "a bill that already has a file keeps its name"
