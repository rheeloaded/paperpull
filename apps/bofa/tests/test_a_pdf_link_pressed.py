"""A Download PDF link whose address is a script, read through a stand-in
page (standin_bank), the page appchamp's second real run on #121 met
(2026-10-27). Its one link's address was "#", with no statement's id in it
or in a data- field. One link is pressed, once a run, the call it makes
for its PDF is heard and learned as a form, that form is asked once more
for the statement pressed, and every statement is then asked with its own
row's call. Anything that does not fit is not pressed or not asked, and
says why in counts. paperpull_core.pressing.click is the stand-in's own
here (standin_bank.press). Every value is invented."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: F401  binds this provider's AppSpec
import bofa_site as site
import standin_bank as sb
from paperpull_core import pressing

LINK = "a statement's Download PDF link"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    site.forget()
    monkeypatch.setattr(pressing, "click", sb.press)
    yield
    site.forget()


def script_page():
    page = sb.Bank()
    page.links = sb.script_links(page.listed["documentList"])
    return page


def pressed(page):
    return [a for a in page.asked if a[0] in sb.PRESSES]


def stop_of(page):
    with pytest.raises(site.NotLearned) as stopped:
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    return stopped.value


def get_call(url, answer="application/pdf", **more):
    return dict({"method": "GET", "url": url, "body": None, "headers": {"accept": "*/*"},
                 "answer": answer}, **more)


# -- learning the call ------------------------------------------------------------

def test_a_link_whose_address_is_a_script_is_pressed_once_and_its_call_learned():
    page = script_page()
    call = site.learn(page)
    assert call.template is None and call.pdf is not None
    assert pressed(page) == [("click", LINK)]
    assert call.facts["pdf_link"] == "pressed" and call.facts["pdf_urls"] == 1
    assert call.facts["pdf_url_kind"] == "json"
    assert call.facts["statements_in_the_pdf_url"] == 1 and call.facts["pdf_url_read_again"] is True
    # Asked once more for the statement pressed, the first link's.
    (again,) = page.pdf_calls
    assert again["method"] == "POST" and again["url"] == sb.PDF_CALL_URL
    assert json.loads(again["body"])["docId"] == "DOC000000000101"
    # The headers the page sent, never the ones the browser sets itself.
    assert again["headers"] == {"content-type": "application/json", "x-standin-csrf": "TOKEN-T"}


def test_every_statement_is_asked_with_its_own_rows_call():
    page = script_page()
    data, day = site.document_bytes(page, account_ref="K-BRAVO-0002", date="2026-01-15",
                                    document_id="DOC000000000201", year="2026")
    assert data.startswith(b"%PDF") and day == "2026-01-15"
    asked = json.loads(page.pdf_calls[-1]["body"])
    assert asked == {"docId": "DOC000000000201", sb.KEY: "K-BRAVO-0002", "lang": "en"}
    assert pressed(page) == [("click", LINK)] and not page.pdfs


def test_a_get_in_a_tab_of_its_own_is_learned_and_the_tab_closed():
    page = script_page()
    url = "https://secure.bankofamerica.com/sample/viewdoc?doc=%s&inline=1"
    page.press_calls = lambda row: [get_call(url % row["docId"])]
    page.press_tabs = lambda row: [url % row["docId"]]
    call = site.learn(page)
    assert call.pdf is not None and call.pdf.method == "GET" and call.pdf.body == ""
    assert page.tabs_closed == [url % "DOC000000000101"]
    site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-02-15",
                        document_id="DOC000000000102", year="2026")
    assert page.pdf_calls[-1]["url"] == url % "DOC000000000102"


def test_a_download_at_an_address_of_the_site_is_the_call_and_is_cancelled():
    """A navigation that downloads, heard as its call and its download,
    with no answer that says PDF."""
    page = script_page()
    url = "https://secure.bankofamerica.com/sample/getdoc?doc=%s"
    page.press_calls = lambda row: [get_call(url % row["docId"], answer="")]
    page.press_downloads = lambda row: [url % row["docId"]]
    call = site.learn(page)
    assert call.pdf is not None and call.facts["downloads"] == 1
    assert call.facts["pdf_files_read"] == 0
    assert page.downloads_ended == [("cancel", url % "DOC000000000101"),
                                    ("delete", url % "DOC000000000101")]


def test_a_pdf_fetched_by_the_page_and_saved_from_a_blob_is_learned_from_the_fetch():
    page = script_page()
    page.press_downloads = lambda row: ["blob:https://secure.bankofamerica.com/0f0e-sample"]
    call = site.learn(page)
    assert call.pdf is not None and call.pdf.method == "POST"
    assert call.facts["downloads_in_the_page"] == 1
    assert ("delete", "blob:https://secure.bankofamerica.com/0f0e-sample") in page.downloads_ended


def test_a_later_reload_presses_nothing_again_and_takes_the_headers_fresh():
    page = script_page()
    site.learn(page)
    page.headers = dict(page.headers, **{"x-standin-csrf": "TOKEN-U"})
    site._learned["at"] = 0.0
    call = site.learned(page, form=True)
    assert page.reloads == 2 and pressed(page) == [("click", LINK)]
    assert call.facts["pdf_link"] == "kept"
    site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                        document_id="DOC000000000101", year="2026")
    assert page.pdf_calls[-1]["headers"]["x-standin-csrf"] == "TOKEN-U"


def test_a_kept_form_call_still_sends_a_form_and_takes_a_pdf_after_fresh_headers():
    """The list call is JSON, so a form call taking its content-type and
    accept would send every later statement's form as JSON (0.59.1 review)."""
    page = script_page()
    form = "docId=%s&lang=en"
    page.press_calls = lambda row: [{
        "method": "POST", "url": sb.PDF_CALL_URL, "body": form % row["docId"],
        "headers": {"content-type": "application/x-www-form-urlencoded", "accept": "application/pdf",
                    "x-standin-csrf": "TOKEN-T"},
        "answer": "application/pdf"}]
    assert site.learn(page).facts["pdf_url_kind"] == "form"
    page.headers = dict(page.headers, **{"x-standin-csrf": "TOKEN-U",
                                         "accept": "application/json, text/plain, */*"})
    site._learned["at"] = 0.0
    assert site.learned(page, form=True).facts["pdf_link"] == "kept"
    site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-02-15",
                        document_id="DOC000000000102", year="2026")
    sent = page.pdf_calls[-1]
    assert sent["body"] == form % "DOC000000000102"
    assert sent["headers"] == {"content-type": "application/x-www-form-urlencoded",
                               "accept": "application/pdf", "x-standin-csrf": "TOKEN-U"}


def test_a_press_that_takes_the_tab_to_its_pdf_goes_back_to_the_statements_page():
    page = script_page()
    page.press_goes_to = "https://secure.bankofamerica.com/sample/viewdoc?doc=DOC000000000101"
    call = site.learn(page)
    assert call.pdf is not None and call.facts["back_to_the_page"] is True
    assert ("back", page.press_goes_to) in page.asked and site.on_statements_page(page)


def test_a_press_that_takes_the_tab_below_the_second_address_goes_back_to_it():
    """The second and third addresses are known by their whole path, so a
    page below either, where a PDF could open, is never taken for the
    statements page and the tab goes back."""
    for start, gone in (
        (sb.SECOND_PAGE_URL, "https://secure.bankofamerica.com/statements-documents/home/viewdoc"),
        (sb.THIRD_PAGE_URL, "https://secure.bankofamerica.com/mycommunications/statements/statement.go/viewdoc"),
    ):
        site.forget()
        page = script_page()
        page.url = start
        page.press_goes_to = gone
        call = site.learn(page)
        assert call.pdf is not None and call.facts["back_to_the_page"] is True
        assert ("back", page.press_goes_to) in page.asked
        assert page.url == start and site.on_statements_page(page)


def test_a_tab_the_press_left_off_the_statements_page_stops_the_run(monkeypatch):
    page = script_page()
    page.press_goes_to = "https://secure.bankofamerica.com/sample/viewdoc?doc=DOC000000000101"
    monkeypatch.setattr(page, "go_back", lambda **k: None)
    with pytest.raises(site.NotThere):
        site.learn(page)


# -- what is never pressed ---------------------------------------------------------

def test_listing_and_diagnose_press_no_link():
    page = script_page()
    site.learn(page, form=False)
    assert not pressed(page)
    site.forget()
    report = site.survey(page, dwell_ms=0)
    assert report["list"]["pdf_link"] == "not pressed" and not report["list"]["pdf_url_kept"]
    assert not pressed(page) and not page.pdf_calls


def test_links_with_their_address_are_read_and_no_link_pressed():
    page = sb.Bank()
    call = site.learn(page)
    assert call.template is not None and call.pdf is None and not pressed(page)
    assert "pdf_link" not in call.facts


def test_a_page_with_some_links_of_an_address_presses_no_link():
    """Not every link opens by a script, so what the page does is not the
    shape the press is for."""
    page = sb.Bank()
    rows = page.listed["documentList"]
    page.links = [{"name": "Download PDF for January Statement for Everyday Checking",
                   "href": sb.LINK_BASE + rows[0]["docId"]}] + sb.script_links(rows)[1:]
    call = site.learn(page)
    assert call.pdf is None and not pressed(page) and "pdf_link" not in call.facts


@pytest.mark.parametrize("name", [
    "Download PDF for January Statement for Everyday Checking - transfer funds",
    "Download PDF for January Statement and update your paperless settings",
    "Download PDF for January Statement for Everyday Checking. Sign out",
])
def test_a_link_with_words_a_blocklist_refuses_is_never_pressed(name):
    page = sb.Bank()
    page.links = [{"name": name, "href": sb.PAGE_URL + "#", "raw": "#", "data": []}]
    call = site.learn(page)
    assert call.facts["pdf_link"] == "refused" and not pressed(page)
    assert stop_of(page).reason == "the pdf link was not pressed"


def test_a_name_the_bank_gave_an_account_is_not_read_as_a_controls_words():
    names = ["Customized Cash Rewards Visa", "October Statement"]
    link = "Download PDF for October Statement for Customized Cash Rewards Visa"
    assert site.is_pdf_link(link, names)
    # The whole name, with no names given, is held to every word.
    assert not site.is_pdf_link(link)
    # Taken out whole only, so a word around it is still read.
    assert not site.is_pdf_link(link + " - Pay now", names)
    assert not site.is_pdf_link("Download PDF for October Statement for Cash Rewards Visas",
                                ["Cash Rewards Visa"])
    # A name that would take the link's own words with it leaves no link.
    assert not site.is_pdf_link("Download PDF for October Statement", ["Download PDF"])
    for name in ("Download PDF", "Download statements", "PDF for October Statement", ""):
        assert not site.is_pdf_link(name, names), name
    assert site.is_pdf_link in site.PRESS_GUARDS


def test_two_links_of_one_name_are_not_pressed():
    page = script_page()
    page.links = page.links[:1] * 2
    call = site.learn(page)
    assert call.facts["pdf_link"] == "several" and not pressed(page)


def test_a_hidden_link_of_the_same_name_is_ignored_while_the_shown_one_is_pressed():
    """include_hidden=True finds links inside a shown row with
    aria-hidden="true", and also any link inside a hidden panel. Only the
    shown link is counted or pressed (#121, 2026-10-31)."""
    page = script_page()
    first = page.links[0]
    page.role_links = [dict(first, visible=False), dict(first, visible=True)]
    call = site.learn(page)
    assert call.facts["pdf_link"] == "pressed" and pressed(page) == [("click", LINK)]
    site.forget()
    page = script_page()
    page.role_links = [dict(x, visible=False) for x in page.links]
    call = site.learn(page)
    assert call.facts["pdf_link"] == "not found" and not pressed(page)


def test_a_link_drawn_as_a_button_is_not_pressed():
    page = script_page()
    page.link_tag = "BUTTON"
    call = site.learn(page)
    assert call.facts["pdf_link"] == "not found" and not pressed(page)


def test_a_link_whose_address_changed_before_the_press_is_not_pressed(monkeypatch):
    page = script_page()
    real = site._a_link_to_press
    looks = []

    def later(el, names):
        looks.append(el)
        if len(looks) > 1:
            el.entry = dict(el.entry, raw=sb.LINK_BASE + "DOC000000000101")
        return real(el, names)
    monkeypatch.setattr(site, "_a_link_to_press", later)
    call = site.learn(page)
    assert call.facts["pdf_link"] == "refused" and not pressed(page) and len(looks) == 2


def test_a_tab_that_left_the_statements_page_before_the_press_is_not_pressed_in(monkeypatch):
    page = script_page()
    real = site.on_statements_page
    seen = []

    def gone(p):
        # On the page when the run starts, gone by the look right before
        # the press.
        seen.append(1)
        return real(p) and len(seen) < 2
    monkeypatch.setattr(site, "on_statements_page", gone)
    with pytest.raises(site.NotThere):
        site.learn(page)
    assert not pressed(page)


def test_something_over_the_link_stops_the_run(monkeypatch):
    def covered(page, el, *, css, what, words, step="press a control", **k):
        assert step == "download a statement" and css == pressing.LINKS
        raise pressing.Covered(step, "something on the page is over the control", [], {})
    page = script_page()
    monkeypatch.setattr(pressing, "click", covered)
    with pytest.raises(pressing.Covered):
        site.learn(page)
    assert not page.pdf_calls and not page.ctx_listeners.get("response")


# -- calls that are not learned ----------------------------------------------------

def test_two_calls_for_a_pdf_are_not_guessed_between():
    page = script_page()
    other = "https://secure.bankofamerica.com/sample/viewdoc?doc=%s"
    page.press_calls = lambda row: sb.json_call(row) + [get_call(other % row["docId"])]
    stop = stop_of(page)
    assert stop.reason == "several pdf urls after the link was pressed" and stop.facts["pdf_urls"] == 2
    assert not page.pdf_calls


def test_a_call_that_holds_no_listed_statements_id_is_not_learned():
    page = script_page()
    page.press_calls = lambda row: [get_call("https://secure.bankofamerica.com/sample/getdoc?t=ONETIMETOKEN1")]
    stop = stop_of(page)
    assert stop.reason == "no statement id in the pdf url"
    assert stop.facts["statements_in_the_pdf_url"] == 0 and not page.pdf_calls


def test_a_call_that_holds_two_statements_ids_is_not_learned():
    page = script_page()
    page.press_calls = lambda row: [get_call(
        "https://secure.bankofamerica.com/sample/getdoc?a=DOC000000000101&b=DOC000000000102")]
    stop = stop_of(page)
    assert stop.facts["statements_in_the_pdf_url"] == 2 and not page.pdf_calls


@pytest.mark.parametrize("change", [
    {"url": "https://secure.bankofamerica.com/samplepg/zone/statements/v1/updateDoc"},
    {"url": "https://secure.bankofamerica.com/samplepg/zone/statements/v1/requestPaperCopy"},
    {"method": "PUT"},
    {"headers": {"content-type": "text/plain"}},
    {"url": "http://secure.bankofamerica.com/samplepg/zone/statements/v1/retrieveDoc"},
])
def test_a_call_that_is_not_one_this_app_asks_again_is_not_learned(change):
    page = script_page()
    page.press_calls = lambda row: [dict(sb.json_call(row)[0], **change)]
    stop = stop_of(page)
    if change.get("url", "").startswith("http:"):
        # Not on the site's own https, so never heard at all.
        assert stop.reason == "no pdf url after the link was pressed"
    else:
        assert stop.reason == "the pdf url is refused"
        assert stop.facts["pdf_url_refused"] is True
    assert not page.pdf_calls


def test_a_call_off_the_site_is_never_heard():
    page = script_page()
    page.press_calls = lambda row: [dict(sb.json_call(row)[0], url="https://evil.test/retrieveDoc")]
    stop = stop_of(page)
    assert stop.reason == "no pdf url after the link was pressed" and stop.facts["urls_read_after_the_link_was_pressed"] == 0


def test_a_call_that_does_not_answer_with_a_pdf_again_is_not_kept():
    page = script_page()
    page.pdf_bytes = b"<html>Sorry</html>"
    stop = stop_of(page)
    assert stop.reason == "no pdf when the pdf url was read again"
    assert stop.facts["pdf_url_read_again"] is False
    # Asked once, for the statement pressed, and nothing more.
    assert len(page.pdf_calls) == 1


def test_a_refusal_of_the_call_asked_again_is_a_call_not_kept_and_no_sign_in():
    """The list answered a moment before, so a 401 to this one call says it
    cannot be asked from the page. Told to sign in again, the person would
    run again and the link would be pressed again for the same answer."""
    page = script_page()
    page.pdf_status = 401
    call = site.learn(page)
    assert call.pdf is None and call.facts["pdf_url_read_again"] is False
    assert stop_of(page).reason == "no pdf when the pdf url was read again"
    assert len(page.pdf_calls) == 1


def test_the_link_is_pressed_once_a_run_even_when_nothing_was_learned():
    page = script_page()
    page.press_calls = lambda row: []
    site.learn(page)
    site._learned["at"] = 0.0
    call = site.learned(page, form=True)
    assert pressed(page) == [("click", LINK)] and page.reloads == 2
    assert call.facts["pdf_link"] == "pressed" and call.facts["pdf_urls"] == 0


def test_the_link_is_pressed_once_a_run_when_the_page_fails_after_the_press(monkeypatch):
    page = script_page()
    real = page.wait_for_timeout
    gone = []

    def closed(ms):
        if pressed(page) and not gone:
            gone.append(1)
            raise RuntimeError("Target page, context or browser has been closed")
        return real(ms)
    monkeypatch.setattr(page, "wait_for_timeout", closed)
    with pytest.raises(RuntimeError):
        site.learn(page)
    # The next statement learns again and presses nothing.
    with pytest.raises(site.NotLearned):
        site.document_bytes(page, account_ref="K-ALPHA-0001", date="2026-01-15",
                            document_id="DOC000000000101", year="2026")
    assert pressed(page) == [("click", LINK)]
    assert not page.ctx_listeners.get("response") and not page.download_listeners


def test_a_tab_the_person_opened_meanwhile_is_left_with_its_download():
    """On the bank's site too, as one opened by hand in those seconds is
    (0.59.1 review)."""
    page = script_page()
    mine = sb.Tab(page, "about:blank", ours=False, downloads=["https://example.test/report.pdf"])
    mine_on_the_site = sb.Tab(page, "https://secure.bankofamerica.com/myaccounts/brain/redirect.go",
                              ours=False)
    page.press_tabs = lambda row: [mine, mine_on_the_site]
    call = site.learn(page)
    assert call.pdf is not None and call.facts["downloads"] == 0
    assert page.tabs_closed == []
    assert not [d for d in page.downloads_ended if "example.test" in d[1]]


def test_a_tab_opened_with_no_opener_at_the_pdf_brought_is_closed():
    """As a link opening in a new tab can be, with no way back to the page."""
    page = script_page()
    url = "https://secure.bankofamerica.com/sample/viewdoc?doc=%s&inline=1"
    page.press_calls = lambda row: [get_call(url % row["docId"])]
    page.press_tabs = lambda row: [sb.Tab(page, url % row["docId"], ours=False)]
    assert site.learn(page).pdf is not None
    assert page.tabs_closed == [url % "DOC000000000101"]


def test_a_value_that_would_change_the_call_is_never_written_as_it_is():
    page = script_page()
    site.learn(page)
    row = dict(sb.STATEMENTS[("K-ALPHA-0001", "2026")][1], docId='DOC0000"x":"y')
    with pytest.raises(site.NotLearned):
        site._ask_pdf(page, site._pdf_learned["pdf"], row)


# -- what a stop writes --------------------------------------------------------------

def test_every_fact_and_reason_of_the_press_keeps_its_name_and_words():
    from paperpull_core.failure import _step
    from paperpull_core.words import shape_tree
    page = script_page()
    page.press_downloads = lambda row: ["blob:https://secure.bankofamerica.com/0f0e-sample"]
    page.press_goes_to = "https://secure.bankofamerica.com/sample/viewdoc?doc=DOC000000000101"
    call = site.learn(page)
    facts = dict(call.facts, pdf_url_refused=True, pdf_url_kept=True)
    for key, value in facts.items():
        assert shape_tree(key) == key, key
        if isinstance(value, str):
            assert shape_tree(value) == value, value
    for value in ("pressed", "refused", "several", "not found", "kept", "not pressed",
                  "get", "other", "json", "form", "download a statement"):
        assert shape_tree(value) == value, value
    cases = [dict(pdf_link=x, pdf_links=1) for x in ("refused", "several", "not found")] + [
        dict(pdf_link="pressed", pdf_links=1, pdf_urls=0),
        dict(pdf_link="pressed", pdf_links=1, pdf_urls=2),
        dict(pdf_link="pressed", pdf_links=1, pdf_urls=1, pdf_url_refused=True),
        dict(pdf_link="pressed", pdf_links=1, pdf_urls=1, statements_in_the_pdf_url=0),
        dict(pdf_link="pressed", pdf_links=1, pdf_urls=1, statements_in_the_pdf_url=1,
             pdf_url_read_again=False)]
    for facts in cases:
        _why, reason = site.not_learned_why(facts)
        assert _step(reason) == reason and shape_tree(reason) == reason, reason
    said = repr(call.facts)
    for value in ("DOC000000000101", "K-ALPHA-0001", "Everyday Checking", "retrieveDoc", "TOKEN-T"):
        assert value not in said, value
