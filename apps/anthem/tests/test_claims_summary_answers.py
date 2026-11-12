"""What the claims list's export may answer, and what it may not be taken for.

The export hands its CSV base64 at result.data.file, named text/csv. A year
whose answer is not that, no file at all, a file named something else, one
that does not decode or one that is not the claims list, did not come, and
taking it for a year with no claim would leave that year's summary out for
good with nothing said. So each of those stops the listing as incomplete,
as does anything that goes wrong in the page. Only an empty file, one of
blank lines, or the claims list's header row alone is a year with no claim.
That empty shape is unconfirmed live, so it is held narrow.

The export's own code is run in a real browser here, with the page's fetch
stood in for, so what it hands back for an answer with no file is the code's
and not a stand-in's. Every name, claim number and amount is invented.
"""
import base64
import json
import sys
from datetime import date
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import anthem_site as site  # noqa: E402
from paperpull_core import intake  # noqa: E402

TODAY = date(2026, 11, 11)
HEADER = "Claim Type,Claim Number,Patient,Service Date,Billed,Your Cost"
CLAIM = "Medical,9000000AA0003,Dana Example,2026-03-04,$120.00,$20.00"


def b64(text) -> str:
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    return base64.b64encode(raw).decode()


class Answers:
    """A page answering every period's export with `answer`, or each
    answer in turn when given a list."""

    def __init__(self, answer):
        self.answers = answer if isinstance(answer, list) else None
        self.answer = answer
        self.asked = []

    def evaluate(self, js, arg=None):
        assert "claims.v1.summaryDownload" in js
        self.asked.append(dict(arg))
        if self.answers is not None:
            return self.answers.pop(0) if self.answers else {"status": 200, "type": "text/csv",
                                                             "file": ""}
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    monkeypatch.setattr(site, "is_anthem_owned_page", lambda page: True)
    monkeypatch.setattr(site, "prime_session", lambda page, force=False: True)


def ok(file, kind="text/csv"):
    return {"status": 200, "type": kind, "file": file}


# -- a year with no claim ----------------------------------------------------

@pytest.mark.parametrize("file", [
    "", b64(""), b64("\r\n"), b64("\r\n \r\n,,\r\n"), b64(HEADER + "\r\n"),
    b64(chr(0xFEFF) + HEADER + "\r\n"), b64(HEADER), b64(HEADER.lower()),
])
def test_an_empty_file_or_the_header_alone_is_a_year_with_no_claim(file):
    page = Answers(ok(file))
    assert site.list_claims_summaries(page, TODAY) == []
    assert len(page.asked) == len(site.claims_summary_periods(TODAY))


@pytest.mark.parametrize("kind", ["text/csv", "text/csv; charset=utf-8", "TEXT/CSV"])
def test_a_year_with_a_claim_is_listed(kind):
    page = Answers([ok(b64(HEADER + "\r\n" + CLAIM + "\r\n"), kind)])
    rows = site.list_claims_summaries(page, TODAY)
    assert [r["doc_id"] for r in rows] == ["ClaimsSummary|2026-11"]
    assert CLAIM in rows[0]["csv"]


# -- an answer that is not a list --------------------------------------------

@pytest.mark.parametrize("answer", [
    {"status": 200, "type": "text/csv"},
    {"status": 200, "type": "text/csv", "file": None},
    {"status": 200, "type": "text/csv", "file": 7},
    {"status": 200, "type": None, "file": ""},
    {"status": 200, "file": b64(HEADER + "\r\n" + CLAIM)},
    ok(b64(HEADER + "\r\n" + CLAIM), "application/json"),
    ok(b64(HEADER + "\r\n" + CLAIM), "text/html"),
    ok(b64(HEADER + "\r\n" + CLAIM), "text/csvx"),
    ok(b64(HEADER + "\r\n" + CLAIM), ""),
    ok("not base64 at all!"),
    ok(b64(HEADER)[:-2] + "*"),
    ok(b64("No claims were found for these dates")),
    ok(b64("Something went wrong\r\nPlease try again")),
    ok(b64("<html><body>Sign in</body></html>")),
])
def test_an_answer_that_is_not_the_claims_list_stops_the_listing(answer):
    page = Answers(answer)
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(page, TODAY)
    assert len(page.asked) == 1


@pytest.mark.parametrize("answer", [None, [], "a string", 0])
def test_an_answer_of_no_shape_stops_the_listing(answer):
    page = Answers({"status": 200})
    page.evaluate = lambda js, arg=None: answer
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(page, TODAY)


@pytest.mark.parametrize("error", [
    RuntimeError("TypeError: Failed to fetch"), RuntimeError(""),
    intake.TooLarge("The answer was larger than PaperPull takes in"),
    TimeoutError("Timeout 30000ms exceeded"),
])
def test_anything_that_goes_wrong_in_the_page_stops_the_listing(error):
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(Answers(error), TODAY)


def test_a_retry_after_a_fresh_session_that_fails_stops_the_listing(monkeypatch):
    primed = []
    monkeypatch.setattr(site, "prime_session", lambda page, force=False: primed.append(force) or True)
    page = Answers([{"status": 401}])
    calls = iter([{"status": 401}, RuntimeError("TypeError: Failed to fetch")])

    def evaluate(js, arg=None):
        got = next(calls)
        if isinstance(got, Exception):
            raise got
        return got
    page.evaluate = evaluate
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(page, TODAY)
    assert primed == [False, True]


# -- the export's own code ---------------------------------------------------

@pytest.fixture()
def browser_page():
    pw = pytest.importorskip("playwright.sync_api")
    try:
        driver = pw.sync_playwright().start()
        browser = driver.chromium.launch(headless=True)
    except Exception as e:
        pytest.skip("no browser to drive: %s" % e)
    ctx = browser.new_context()
    ctx.route("**/*", lambda route: route.abort())
    page = ctx.new_page()
    page.set_content("<!doctype html><html><body></body></html>")
    yield page
    browser.close()
    driver.stop()


def answered(page, data, content_type="application/json"):
    """The page's fetch stood in for, answering the export with `data` as
    result.data, and the page holding a captured session."""
    body = json.dumps({"result": {"data": data}})
    page.evaluate("""([body, ct]) => {
      window.__eobHeaders = {};
      window.fetch = async () => new Response(body, {status: 200, headers: {'content-type': ct}});
    }""", [body, content_type])


@pytest.mark.parametrize("data", [{}, {"type": "text/csv"}, {"type": "text/csv", "file": None},
                                  {"type": "text/csv", "file": 12}, None])
def test_the_export_code_hands_back_no_file_when_the_answer_has_none(browser_page, data):
    answered(browser_page, data)
    res = intake.evaluate(browser_page, site._CLAIMS_EXPORT_JS,
                          {"start": "2026-01-01", "end": "2026-11-11"})
    assert res["status"] == 200 and res["file"] is None
    with pytest.raises(site.ListingIncomplete):
        site.list_claims_summaries(browser_page, TODAY)


def test_the_export_code_hands_back_an_empty_file_as_one(browser_page):
    answered(browser_page, {"type": "text/csv", "file": ""})
    res = intake.evaluate(browser_page, site._CLAIMS_EXPORT_JS,
                          {"start": "2026-01-01", "end": "2026-11-11"})
    assert res == {"status": 200, "type": "text/csv", "file": ""}
    assert site.list_claims_summaries(browser_page, TODAY) == []


def test_the_export_code_hands_back_a_file_and_its_type(browser_page):
    csv = HEADER + "\r\n" + CLAIM + "\r\n"
    answered(browser_page, {"type": "text/csv", "file": b64(csv)})
    rows = site.list_claims_summaries(browser_page, TODAY)
    assert [r["doc_id"] for r in rows] == ["ClaimsSummary|%s" % p["period"]
                                           for p in site.claims_summary_periods(TODAY)]
    assert rows[0]["csv"] == csv


# -- what is sent ------------------------------------------------------------

def test_the_app_hands_the_export_two_dates_and_nothing_else():
    page = Answers(ok(""))
    site.list_claims_summaries(page, TODAY)
    assert page.asked == [{"start": p["start"], "end": p["end"]}
                          for p in site.claims_summary_periods(TODAY)]
    for arg in page.asked:
        assert date.fromisoformat(arg["start"]).isoformat() == arg["start"]
        assert date.fromisoformat(arg["end"]).isoformat() == arg["end"]


def test_the_export_is_one_post_of_the_dates_and_its_own_options(browser_page):
    answered(browser_page, {"type": "text/csv", "file": ""})
    browser_page.evaluate("""() => {
      const answer = window.fetch;
      window.__asked = [];
      window.fetch = async (url, init) => {
        window.__asked.push({url: String(url), method: init.method, body: init.body});
        return answer(url, init);
      };
    }""")
    site.list_claims_summaries(browser_page, TODAY)
    asked = browser_page.evaluate("() => window.__asked")
    periods = site.claims_summary_periods(TODAY)
    assert len(asked) == len(periods)
    for got, p in zip(asked, periods):
        assert got["url"] == ("https://membersecure-polaris.anthem.com/api/claims/trpc/"
                              "claims.v1.summaryDownload")
        assert got["method"] == "POST"
        assert json.loads(got["body"]) == {"start": p["start"], "end": p["end"],
                                           "sort": ["-end"], "mediaType": "csv", "filters": []}
