"""Bank of America's statements page, as the two recordings on #121 showed
it, read through a stand-in page (standin_bank). The list call and the PDF
links are learned from the page itself, every account and year is asked
for the way the page asks, and anything that does not fit stops the run
rather than being guessed at. The one press is the Statements heading, when
the page leaves it shut, and paperpull_core.pressing.click is the stand-in's
own here (standin_bank.press). Every value is invented."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_site as site
import standin_bank as sb
from paperpull_core import pressing


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    site.forget()
    monkeypatch.setattr(pressing, "click", sb.press)
    yield
    site.forget()


def no_presses(page):
    assert not [a for a in page.asked if a[0] in sb.PRESSES], page.asked
    assert not [a for a in page.asked if a[0] == "goto"], page.asked


# -- learning the page's own call ---------------------------------------------

def test_the_list_call_is_learned_from_one_reload_and_nothing_is_pressed():
    page = sb.Bank()
    call = site.learn(page)
    assert page.reloads == 1
    assert call.url == sb.LIST_URL
    assert call.account_key == sb.KEY
    assert call.statements_category == "CAT-STMT"
    assert call.years == ["2026", "2025"]
    assert [a[sb.KEY] for a in call.accounts] == ["K-ALPHA-0001", "K-BRAVO-0002"]
    # The page's own headers are sent again, never the ones the browser sets.
    assert call.headers == {"content-type": "application/json", "x-standin-csrf": "TOKEN-T"}
    assert call.template is not None and call.links == 2
    no_presses(page)
    assert not page.listeners, "the listener was left on the page"


def test_a_tab_off_the_statements_page_is_never_reloaded():
    page = sb.Bank(url="https://secure.bankofamerica.com/myaccounts/overview/?k=X")
    with pytest.raises(site.NotThere):
        site.learn(page)
    assert page.reloads == 0


def test_a_page_of_another_site_is_not_the_statements_page():
    assert not site.on_statements_page(sb.Bank(url="https://evil.test/sample-zz-stmts-docs/"))
    assert not site.on_statements_page(sb.Bank(url="https://www.bankofamerica.com/sample-zz-stmts-docs/"))
    assert not site.on_statements_page(sb.Bank(password=1))
    assert site.on_statements_page(sb.Bank())


@pytest.mark.parametrize("url", [
    sb.PAGE_URL,
    sb.SECOND_PAGE_URL,
    "https://secure.bankofamerica.com/statements-documents/home/",
    sb.THIRD_PAGE_URL,
    "https://secure.bankofamerica.com/mycommunications/statements/statement.go",
])
def test_both_addresses_of_the_statements_page_are_it(url):
    """A second tester's window was on Statements & Documents at
    /statements-documents/home/, and the credit card statements page in the
    second recording is at /mycommunications/statements/statement.go (#121)."""
    assert site.is_statements_address(url)
    assert site.on_statements_page(sb.Bank(url=url))


@pytest.mark.parametrize("url", [
    "https://www.bankofamerica.com/statements-documents/home/",
    "https://secure.bankofamerica.com.evil.test/statements-documents/home/",
    "http://secure.bankofamerica.com/statements-documents/home/",
    "https://secure.bankofamerica.com/statements-documents/",
    # Only the path as the screenshot and recording showed it, letter for letter.
    "https://secure.bankofamerica.com/statements-documents/home",
    "https://secure.bankofamerica.com/Statements-Documents/Home/",
    "https://secure.bankofamerica.com/statements-documents/home/viewdoc",
    "https://secure.bankofamerica.com/statements-documents/home/settings/",
    "https://secure.bankofamerica.com/sample/statements-documents/home/",
    "https://secure.bankofamerica.com/statements-documents-old/home/",
    "https://secure.bankofamerica.com/myaccounts/overview/?next=/statements-documents/home/",
    "https://secure.bankofamerica.com/myaccounts/overview/#/statements-documents/home/",
    "https://www.bankofamerica.com/mycommunications/statements/statement.go",
    "http://secure.bankofamerica.com/mycommunications/statements/statement.go",
    "https://secure.bankofamerica.com/mycommunications/statements/",
    "https://secure.bankofamerica.com/mycommunications/statements/statement.go/",
    "https://secure.bankofamerica.com/mycommunications/statements/statement.go/viewdoc",
    "https://secure.bankofamerica.com/MyCommunications/Statements/statement.go",
    "https://secure.bankofamerica.com/mycommunications/statements/statementXgo",
    "https://secure.bankofamerica.com/myaccounts/overview/?next=/mycommunications/statements/statement.go",
])
def test_no_other_address_is_taken_for_the_second_one(url):
    assert not site.is_statements_address(url)
    assert not site.on_statements_page(sb.Bank(url=url))


def test_the_second_address_is_reloaded_once_and_its_list_call_learned():
    for url in (sb.SECOND_PAGE_URL, sb.THIRD_PAGE_URL):
        site.forget()
        page = sb.Bank(url=url)
        call = site.learn(page)
        assert page.reloads == 1 and call.url == sb.LIST_URL
        assert call.template is not None and call.links == 2
        no_presses(page)
        assert not site.on_statements_page(sb.Bank(url=url, password=1))


def test_a_page_that_makes_no_list_call_is_not_guessed_at():
    page = sb.Bank()
    page.first_url = "https://secure.bankofamerica.com/sample/standin/zone/other/v1/listThings"
    with pytest.raises(site.NotLearned):
        site.learn(page)


@pytest.mark.parametrize("url", [
    "https://www.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "https://secure.bankofamerica.com.evil.test/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "http://secure.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments",
    "https://secure.bankofamerica.com/samplepg/standinsamplezz/zone/statements/v1/lookupDocuments?x=1",
])
def test_only_the_list_call_on_the_secure_host_is_heard(url):
    page = sb.Bank()
    page.first_url = url
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_sign_in_answer_is_a_session_that_ended():
    page = sb.Bank()
    page.first_status = 401
    page.listed = {"error": "signed out"}
    with pytest.raises(site.SessionExpired):
        site.learn(page)


@pytest.mark.parametrize("body", [
    {sb.KEY: "K-ALPHA-0001", "other": "x", "docCategoryId": "CAT-STMT", "year": "2026"},
    {"docCategoryId": "CAT-STMT", "year": "2026"},
    {sb.KEY: "K-BRAVO-0002", "docCategoryId": "CAT-STMT", "year": "2026"},
    {sb.KEY: "", "docCategoryId": "CAT-STMT", "year": "2026"},
])
def test_an_account_key_that_cannot_be_told_is_not_guessed(body):
    """Two names besides the known ones, none, or one whose value is not
    the selected account's, and nothing is asked."""
    page = sb.Bank()
    page.first_body = body
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_with_no_statements_category_is_not_guessed_at():
    page = sb.Bank()
    page.listed = dict(page.listed, documentCategoryList=[{"docCategoryName": "Tax Documents",
                                                           "docCategoryId": "CAT-TAX"}])
    with pytest.raises(site.NotLearned):
        site.learn(page)


# -- every account, every year -------------------------------------------------

def test_every_account_and_year_is_asked_the_way_the_page_asks():
    page = sb.Bank()
    rows = site.collect_documents(page)
    asked = [(b["body"][sb.KEY], b["body"]["year"]) for b in page.lists]
    assert asked == [("K-ALPHA-0001", "2026"), ("K-ALPHA-0001", "2025"),
                     ("K-BRAVO-0002", "2026"), ("K-BRAVO-0002", "2025")]
    for b in page.lists:
        assert b["url"] == sb.LIST_URL
        assert b["body"]["docCategoryId"] == "CAT-STMT" and b["body"]["lang"] == "en"
        assert "cookie" not in b["headers"]
    assert [(r["account"], r["date"], r["document_id"], r["year"]) for r in rows] == [
        ("Everyday Checking", "2025-12-15", "DOC000000000091", "2025"),
        ("Everyday Checking", "2026-01-15", "DOC000000000101", "2026"),
        ("Everyday Checking", "2026-02-15", "DOC000000000102", "2026"),
        ("Travel Card", "2026-01-15", "DOC000000000201", "2026"),
    ]
    assert all(r["category"] == "Statement" for r in rows)
    no_presses(page)


def test_a_scoped_run_asks_only_its_years():
    page = sb.Bank()
    site.collect_documents(page, keep=lambda year: year == "2026")
    assert {b["body"]["year"] for b in page.lists} == {"2026"}


def test_a_row_of_another_category_is_left_out():
    page = sb.Bank()
    other = sb.row("DOC000000000301", sb.ACCOUNTS[0], "2026-01-15", category="CAT-TAX")
    page.answer_list = lambda body: (list(sb.STATEMENTS.get((body[sb.KEY], body["year"]), []))
                                     + ([other] if body[sb.KEY] == "K-ALPHA-0001" else []))
    ids = [r["document_id"] for r in site.collect_documents(page)]
    assert "DOC000000000301" not in ids and len(ids) == 4


def test_a_statement_under_another_accounts_key_stops_the_list():
    """In this account's answer it is no statement of this account, and an
    account written another way would leave every statement out."""
    page = sb.Bank()
    stray = sb.row("DOC000000000302", sb.ACCOUNTS[1], "2026-01-20")
    page.answer_list = lambda body: (list(sb.STATEMENTS.get((body[sb.KEY], body["year"]), []))
                                     + ([stray] if body[sb.KEY] == "K-ALPHA-0001" else []))
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_year_named_only_by_an_accounts_own_answer_is_asked_too():
    page = sb.Bank()
    page.years_for = lambda body: ["2026", "2025", "2024"] if body[sb.KEY] == "K-BRAVO-0002" else sb.YEARS
    site.collect_documents(page)
    asked = [(b["body"][sb.KEY], b["body"]["year"]) for b in page.lists]
    assert ("K-BRAVO-0002", "2024") in asked and ("K-ALPHA-0001", "2024") not in asked
    assert len(asked) == len(set(asked)), "a year was asked twice"


def test_an_answer_that_says_another_status_or_an_error_stops_the_list():
    page = sb.Bank()
    page.status_for = lambda body: "ERROR" if body[sb.KEY] == "K-BRAVO-0002" else "SUCCESS"
    with pytest.raises(site.ListCut):
        site.collect_documents(page)
    page = sb.Bank()
    page.errors_for = lambda body: [{"code": "E1"}] if body["year"] == "2025" else []
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_an_account_without_a_key_is_not_left_out_quietly():
    page = sb.Bank()
    keyless = {k: v for k, v in sb.ACCOUNTS[1].items() if k != sb.KEY}
    page.listed = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")], accounts=[sb.ACCOUNTS[0], keyless])
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_call_the_page_could_not_make_stops_the_list():
    page = sb.Bank()
    page.list_raises = RuntimeError("TypeError: Failed to fetch")
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


@pytest.mark.parametrize("path", [
    "/samplepg/standinsamplezz/zone/statements/v1/deleteDocuments",
    "/samplepg/standinsamplezz/zone/statements/v1/updateDocuments",
    "/sample/standin/zone/statements/v1/lookupDocuments",
])
def test_a_call_naming_a_change_or_of_another_shape_is_never_heard(path):
    page = sb.Bank()
    page.first_url = "https://secure.bankofamerica.com" + path
    with pytest.raises(site.NotLearned):
        site.learn(page)


def test_a_list_call_whose_body_was_not_json_is_not_heard():
    page = sb.Bank()
    page.headers = dict(page.headers, **{"content-type": "application/x-www-form-urlencoded"})
    with pytest.raises(site.NotLearned):
        site.learn(page)


@pytest.mark.parametrize("bad", [
    {"date": "", "dateString": ""},
    {"date": "2026-02-30"},
    {"date": "2026-01-15", "dateString": "Jan 16, 2026"},
    {"docId": ""},
    {"docId": 12345},
    {"docCategoryId": ""},
])
def test_a_statement_row_it_cannot_read_stops_the_list(bad):
    """A statement it cannot read is never left out of a list taken as
    whole, so the run stops instead."""
    page = sb.Bank()
    broken = dict(sb.row("DOC000000000401", sb.ACCOUNTS[0], "2026-03-15"), **bad)
    page.answer_list = lambda body: [broken] if body["year"] == "2026" else []
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_list_call_that_fails_part_way_stops_the_list():
    page = sb.Bank()
    page.list_status = 500
    with pytest.raises(site.ListCut):
        site.collect_documents(page)


def test_a_sign_in_part_way_through_the_list_is_a_session_that_ended():
    page = sb.Bank()
    page.list_status = 403
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)


# -- the PDF link's form --------------------------------------------------------

ROW = sb.row("DOC000000000101", sb.ACCOUNTS[0], "2026-01-15")


@pytest.mark.parametrize("href", [
    "https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101",
    "https://secure.bankofamerica.com/sample/getpdf?a=K-ALPHA-0001&doc=DOC000000000101&t=T1",
    "https://secure.bankofamerica.com/sample/DOC000000000101/view.pdf",
])
def test_a_link_comes_out_of_its_form_and_another_row_takes_the_same_form(href):
    form = site.template_of(href, ROW)
    assert form is not None and site.fill(form, ROW) == href
    other = sb.row("DOC000000000201", sb.ACCOUNTS[1], "2026-01-15")
    filled = site.fill(form, other)
    assert "DOC000000000201" in filled and "DOC000000000101" not in filled
    if "K-ALPHA-0001" in href:
        assert "K-BRAVO-0002" in filled and "K-ALPHA-0001" not in filled


def test_a_docid_written_escaped_is_filled_escaped():
    escaped_row = dict(ROW, docId="DOC/0000+0101")
    href = "https://secure.bankofamerica.com/sample/getpdf?doc=DOC%2F0000%2B0101"
    form = site.template_of(href, escaped_row)
    assert site.fill(form, escaped_row) == href
    assert site.fill(form, dict(escaped_row, docId="DOC/9999+0001")).endswith("DOC%2F9999%2B0001")


def test_a_docid_found_only_inside_a_longer_run_makes_no_form():
    short = dict(ROW, docId="DOC0099")
    assert site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=DOC00992", short) is None


def test_a_value_that_would_change_the_address_is_never_written_as_it_is():
    form = site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101", ROW)
    assert site.fill(form, dict(ROW, docId="DOC00/../x?y=1")) is None
    assert site.fill(form, dict(ROW, docId="DOC000000000555")).endswith("doc=DOC000000000555")


def test_a_link_without_its_rows_docid_has_no_form():
    assert site.template_of("https://secure.bankofamerica.com/sample/getpdf?doc=SOMETHINGELSE", ROW) is None
    assert site.learn_template([ROW], ["javascript:void(0)"]) == (None, 0)


def test_links_from_two_forms_are_not_taken():
    rows = [ROW, sb.row("DOC000000000102", sb.ACCOUNTS[0], "2026-02-15")]
    links = ["https://secure.bankofamerica.com/sample/getpdf?doc=DOC000000000101",
             "https://secure.bankofamerica.com/other/fetch/DOC000000000102"]
    assert site.learn_template(rows, links) == (None, 2)


def test_a_page_that_draws_no_link_it_can_read_learns_no_form():
    """A link whose address is a script, whose press asks for nothing."""
    page = sb.Bank()
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "javascript:void(0)"}]
    page.press_calls = lambda row: []
    call = site.learn(page)
    assert call.template is None and call.pdf is None
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs and not page.pdf_calls


def test_a_link_off_the_site_is_never_read():
    page = sb.Bank()
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "https://evil.test/getpdf?doc=DOC000000000101"}]
    assert site.download_links(page) == []


# -- the Statements heading ------------------------------------------------------

def pressed(page):
    return [a for a in page.asked if a[0] in sb.PRESSES]


def test_a_shut_statements_heading_is_opened_once_and_its_links_learned():
    """appchamp's first real run (#121, 2026-10-26). The reload left the
    Statements heading shut, the page drew no Download PDF link, and every
    statement stopped with nothing saved. Opening it is the press both
    recordings made first."""
    page = sb.Bank(heading="shut")
    call = site.learn(page)
    assert pressed(page) == [("click", "the Statements heading")]
    assert call.template is not None and call.links == 2
    assert call.facts["statements_heading"] == "opened" and call.facts["times_the_list_was_read"] == 2
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000000201", year="2026")
    assert data.startswith(b"%PDF") and day == "2026-01-15"
    assert pressed(page) == [("click", "the Statements heading")], "the heading was pressed again"
    assert not page.listeners, "the listener was left on the page"


def test_the_rows_the_heading_draws_are_learned_from_its_own_answer():
    """The reload's own answer listed other rows (appchamp's listed 7 and
    then 1), so the links are matched to the rows of every answer heard."""
    page = sb.Bank(heading="shut")
    page.listed = sb.answer([sb.row("DOC000000000777", sb.ACCOUNTS[0], "2026-03-01",
                                    "Tax Form", category="CAT-TAX")])
    page.opened = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")])
    call = site.learn(page)
    assert call.template is not None and call.facts["rows_read"] == 3


def test_an_open_heading_is_never_pressed():
    page = sb.Bank()
    page.links = []
    call = site.learn(page)
    assert not pressed(page) and call.facts["statements_heading"] == "already expanded"
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert "even with its Statements heading open" in str(stopped.value)
    assert stopped.value.facts["pdf_links"] == 0 and not page.pdfs


@pytest.mark.parametrize("how,state", [
    (dict(heading=None), "not found"),
    (dict(heading="several"), "several"),
    (dict(heading="shut", controls=""), "refused"),
    (dict(heading="shut", title="Pay your bill"), "refused"),
    (dict(heading="shut", label="Statements & Documents"), "refused"),
    (dict(heading="shut", form=True), "refused"),
])
def test_a_heading_that_is_not_the_one_is_never_pressed(how, state):
    """No heading, two of the name, one that names no list it opens, one
    with a label the guard refuses, or one a press would submit a form
    with. Nothing is pressed and nothing guessed."""
    page = sb.Bank(heading=how["heading"])
    for name in ("controls", "title", "label", "form"):
        if name in how:
            setattr(page.heading_el, name, how[name])
    call = site.learn(page)
    assert not pressed(page) and call.template is None
    assert call.facts["statements_heading"] == state
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert "could not be opened (%s)" % state in str(stopped.value)


def test_the_heading_guard_takes_the_whole_name_only():
    assert site.is_statements_heading("Statements") and site.is_statements_heading(" Statements ")
    for name in ("Statements & Documents", "Request statements", "Statements and pay",
                 "Tax Documents", "", "statement"):
        assert not site.is_statements_heading(name), name
    assert site.is_statements_heading in site.PRESS_GUARDS


def test_links_that_hide_their_address_are_counted_and_not_guessed():
    """A link whose address is a script and whose statement's id sits only
    in a data- field, the shape a page has when a script of its own opens
    the PDF. One is pressed, and when the press asks for nothing the stop
    says so in counts, and nothing is asked for."""
    page = sb.Bank()
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": "javascript:void(0)", "raw": "javascript:void(0)",
                   "data": ["x", "DOC000000000101"]},
                  {"name": "Download PDF for February Statement for Everyday Checking",
                   "href": sb.PAGE_URL + "#", "raw": "#", "data": ["DOC000000000102"]}]
    page.press_calls = lambda row: []
    call = site.learn(page)
    assert call.template is None and call.pdf is None
    assert pressed(page) == [("click", "a statement's Download PDF link")]
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert "brought no PDF this app could hear" in str(stopped.value)
    assert stopped.value.reason == "no pdf url after the link was pressed"
    facts = stopped.value.facts
    assert (facts["pdf_links"], facts["links_to_no_page"], facts["links_to_this_page"],
            facts["links_with_an_id"], facts["links_with_an_id_elsewhere"]) == (2, 1, 1, 0, 2)
    assert (facts["pdf_link"], facts["pdf_urls"], facts["urls_read_after_the_link_was_pressed"]) == ("pressed", 0, 0)
    assert not page.pdfs and not page.pdf_calls
    said = repr(facts)
    for value in ("DOC000000000101", "javascript", "K-ALPHA-0001", "Everyday Checking"):
        assert value not in said, value


def test_a_heading_shut_again_by_a_later_reload_is_opened_again():
    """A long run hears the page again after FRESH_SECONDS, and that reload
    shuts the heading as the first one did."""
    page = sb.Bank(heading="shut")
    site.learn(page)
    site.learn(page)
    assert pressed(page) == [("click", "the Statements heading")] * 2 and page.reloads == 2


def test_listing_alone_presses_nothing_and_a_download_then_opens_the_heading():
    """Login and Discover only list, and a list needs no PDF link. The first
    statement asked for hears the page again, with the heading opened."""
    page = sb.Bank(heading="shut")
    rows = site.collect_documents(page)
    assert len(rows) == 4 and not pressed(page)
    assert site.learned(page).facts["statements_heading"] == "not pressed"
    data, _day = site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                                     document_id="DOC000000000101", year="2026")
    assert data.startswith(b"%PDF")
    assert pressed(page) == [("click", "the Statements heading")] and page.reloads == 2


def test_a_statement_both_answers_list_is_matched_to_the_row_it_was_drawn_from():
    """The reload's answer and the press's both list January, with another
    value in a field the link carries. The link was drawn from the press's
    row, so that field is part of the form and not the reload's value."""
    page = sb.Bank(heading="shut")
    jan = sb.STATEMENTS[("K-ALPHA-0001", "2026")][0]
    page.listed = sb.answer([dict(jan, source="SRCFROMRELOAD")])
    page.opened = sb.answer([dict(jan, source="SRCFROMPRESS")])
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": sb.LINK_BASE + jan["docId"] + "&s=SRCFROMPRESS"}]
    call = site.learn(page)
    assert call.template == sb.LINK_BASE + "\x00docId\x00&s=\x00source\x00"


def test_a_press_answer_heard_after_the_rows_are_drawn_is_waited_for():
    page = sb.Bank(heading="shut")
    page.press_answer = "late"
    page.listed = sb.answer([sb.row("DOC000000000777", sb.ACCOUNTS[0], "2026-03-01", "Tax Form",
                                    category="CAT-TAX")])
    page.opened = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")])
    call = site.learn(page)
    assert call.template is not None and call.facts["list_read_after_the_heading"] is True


def test_a_press_whose_list_is_never_heard_says_so():
    page = sb.Bank(heading="shut")
    page.press_answer = "never"
    page.listed = sb.answer([sb.row("DOC000000000777", sb.ACCOUNTS[0], "2026-03-01", "Tax Form",
                                    category="CAT-TAX")])
    page.opened = sb.answer(sb.STATEMENTS[("K-ALPHA-0001", "2026")])
    call = site.learn(page)
    assert call.template is None and call.facts["list_read_after_the_heading"] is False
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert "did not hear it ask for" in str(stopped.value)
    assert stopped.value.reason == "the list was not read after the heading"


def test_a_sign_in_answer_to_the_press_is_a_session_that_ended():
    page = sb.Bank(heading="shut")
    page.press_status = 401
    with pytest.raises(site.SessionExpired):
        site.learn(page)
    assert not page.listeners


@pytest.mark.parametrize("title", ["Opt in to eStatements", "Turn on Statements",
                                   "Sign in to Statements"])
def test_a_heading_with_a_settings_or_sign_in_label_is_never_pressed(title):
    """Words the blocklist itself lets through and the settings and sign-in
    lists refuse, as is_safe_control does."""
    assert not site.FORBIDDEN_CONTROL_RE.search(title)
    page = sb.Bank(heading="shut")
    page.heading_el.title = title
    call = site.learn(page)
    assert not pressed(page) and call.facts["statements_heading"] == "refused"


def test_a_heading_the_page_opened_itself_meanwhile_is_not_pressed_shut():
    page = sb.Bank(heading="shut")
    el = page.heading_el
    real = el.get_attribute
    el.get_attribute = lambda name: "true" if name == "aria-expanded" else real(name)
    call = site.learn(page)
    assert not pressed(page) and call.facts["statements_heading"] == "already expanded"


def test_a_tab_that_left_the_statements_page_is_not_pressed_in(monkeypatch):
    page = sb.Bank(heading="shut")
    asked = []
    real = site.on_statements_page

    def moves_away(p):
        asked.append(1)
        return real(p) and len(asked) < 2
    monkeypatch.setattr(site, "on_statements_page", moves_away)
    with pytest.raises(site.NotThere):
        site.learn(page)
    assert not pressed(page) and not page.listeners


def test_a_link_that_matches_no_listed_statement_takes_no_form():
    """Every link the page drew comes out of the one form, or none is taken."""
    page = sb.Bank()
    jan = sb.STATEMENTS[("K-ALPHA-0001", "2026")][0]
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": sb.LINK_BASE + jan["docId"]},
                  {"name": "Download PDF for March Statement for Everyday Checking",
                   "href": sb.LINK_BASE + "DOC000000000999"}]
    call = site.learn(page)
    assert call.template is None and call.facts["links_with_no_row"] == 1
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert stopped.value.reason == "pdf links with no row"


def test_links_the_page_drew_on_its_own_are_read_and_nothing_pressed():
    """The heading is pressed only for want of a link. A page that drew its
    Download PDF links, with the heading shut or open, is never pressed."""
    page = sb.Bank(heading="shut")
    page.links_while_shut = True
    call = site.learn(page)
    assert not pressed(page) and call.template is not None
    assert call.facts["statements_heading"] == "not pressed"


def test_every_fact_a_survey_writes_keeps_its_name_and_words():
    """Diagnose writes its file through the word list, and a name or a word
    off it comes out as its shape (links_to_a_mark was links_to_a_aaaa)."""
    from paperpull_core.words import shape_tree
    page = sb.Bank(heading="shut")
    call = site.learn(page)
    for key, value in call.facts.items():
        assert shape_tree(key) == key, key
        if isinstance(value, str):
            assert shape_tree(value) == value, value
    for state in ("already expanded", "opened", "not found", "several", "refused",
                  "not pressed", "expand the statements heading", "download a statement"):
        assert shape_tree(state) == state, state


def test_every_reason_the_failure_file_gets_is_one_it_keeps():
    from paperpull_core.words import shape_tree
    from paperpull_core.failure import _step
    cases = [dict(pdf_links=0, statements_heading="opened"),
             dict(pdf_links=0, statements_heading="not found"),
             dict(pdf_links=2, forms=0, statements_heading="opened",
                  list_read_after_the_heading=False),
             dict(pdf_links=2, forms=0), dict(pdf_links=2, forms=2),
             dict(pdf_links=2, forms=1, links_with_no_row=1), dict(pdf_links=2, forms=1)]
    for facts in cases:
        _why, reason = site.not_learned_why(facts)
        assert _step(reason) == reason and shape_tree(reason) == reason, reason
    for key in site.link_facts([], []):
        assert shape_tree(key) == key, key


# -- one statement's PDF --------------------------------------------------------

def test_a_statement_is_asked_for_at_its_own_rows_address():
    page = sb.Bank()
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000000201", year="2026")
    assert data.startswith(b"%PDF") and day == "2026-01-15"
    assert page.pdfs == [sb.LINK_BASE + "DOC000000000201"]
    no_presses(page)


def test_a_statement_no_longer_listed_is_not_asked_for():
    page = sb.Bank()
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000999999", year="2026")
    assert data is None and not page.pdfs
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-16",
                                    document_id="DOC000000000201", year="2026")
    assert data is None and not page.pdfs


def test_a_sign_in_instead_of_a_pdf_is_a_session_that_ended():
    page = sb.Bank()
    page.pdf_status = 401
    with pytest.raises(site.SessionExpired):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_pdf_that_ended_up_off_the_site_is_not_taken():
    page = sb.Bank()
    page.pdf_final_url = "https://evil.test/landing"
    with pytest.raises(site.SessionExpired):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_row_found_again_by_its_id_is_held_to_what_a_list_row_is():
    """A row under the same docId but of another category is not this
    statement, and nothing is asked for."""
    page = sb.Bank()
    taxed = sb.row("DOC000000000201", sb.ACCOUNTS[1], "2026-01-15", category="CAT-TAX")
    page.answer_list = lambda body: [taxed] if body[sb.KEY] == "K-BRAVO-0002" else []
    data, _day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                     document_id="DOC000000000201", year="2026")
    assert data is None and not page.pdfs


def test_a_statement_the_page_could_not_ask_for_stops_the_run():
    page = sb.Bank()
    page.pdf_raises = RuntimeError("TypeError: Failed to fetch")
    with pytest.raises(site.ListCut):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")


def test_a_form_on_another_host_than_the_pages_own_links_is_never_asked():
    page = sb.Bank()
    call = site.learn(page)
    call.template = "https://other.bankofamerica.com/getpdf?doc=\x00docId\x00"
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs


def test_a_form_that_would_leave_the_site_is_never_asked():
    page = sb.Bank()
    call = site.learn(page)
    call.template = "https://evil.test/getpdf?doc=\x00docId\x00"
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert not page.pdfs


# -- dates ---------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("2026-01-15", "2026-01-15"), ("2026-01-15T00:00:00", "2026-01-15"),
    ("01/15/2026", "2026-01-15"), ("1/5/26", "2026-01-05"), ("Jan 15, 2026", "2026-01-15"),
    ("January 15, 2026", "2026-01-15"), ("2026-02-30", ""), ("13/01/2026", ""),
    ("yesterday", ""), ("", ""), (None, ""),
])
def test_dates_are_read_each_way_a_list_writes_them(text, want):
    assert site.parse_date(text) == want


def test_a_day_named_in_the_file_name_is_read():
    assert site.date_in_file_name('attachment; filename="eStmt_2026-01-15.pdf"') == "2026-01-15"
    assert site.date_in_file_name("attachment; filename=eStmt_2026-02-30.pdf") == ""
    assert site.date_in_file_name("inline") == ""


# -- what Diagnose may write -----------------------------------------------------

def test_what_was_learned_is_said_in_names_and_counts_never_a_value():
    page = sb.Bank()
    said = repr(site.learned_summary(site.learn(page)))
    for value in ("K-ALPHA-0001", "K-BRAVO-0002", "DOC000000000101", "TOKEN-T", "STANDINTOKEN",
                  "Everyday Checking", "Travel Card", "lookupDocuments", "getpdf", "2026-01-15"):
        assert value not in said, value
    assert "'pdf_form_learned': True" in said and "'accounts': 2" in said


def test_the_survey_reads_the_statements_page_and_presses_nothing():
    page = sb.Bank()
    report = site.survey(page, dwell_ms=0)
    assert report["list"]["accounts"] == 2 and report["pages"][0]["on_site"]
    assert "k=" not in report["pages"][0]["url"]
    no_presses(page)


def test_the_survey_of_another_page_reads_no_list():
    page = sb.Bank(url="https://secure.bankofamerica.com/myaccounts/overview/")
    report = site.survey(page, dwell_ms=0)
    assert report["list"]["stopped"] == "NotThere" and page.reloads == 0
