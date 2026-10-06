"""A failure file and a Diagnose survey keep no word off the word list.

Both were built from a list of what may leave, and most of what they carry
is a count or a word of ours. Four channels still copied a name or a token
rather than a fixed word. A request's path and the keys of a JSON answer
were kept unless they looked like an id, and an id of thirteen letters and
one digit did not. The selector census and the journal took their entries'
names from the page's answer rather than from the app's own table, and any
script on the page can change an answer. And a phrase an app handed over
was kept when it was lowercase letters, which a page's words can be too.

Each test here puts an invented value made of letters and digits through
one of those channels. Each failed on the files as they were.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paperpull_core import api_census, failure  # noqa: E402
from paperpull_core.journal import Journal  # noqa: E402

MERCHANT = "QZXKRWPTKMV4N"        # letters and one digit, a merchant id's shape
SURNAME = "zorvexquill"           # lowercase, the way _STEP_RE let it through
CANARIES = (MERCHANT, SURNAME)


def no_canary_in(path):
    text = Path(path).read_text(encoding="utf-8").lower()
    for canary in CANARIES:
        assert canary.lower() not in text, "%s came out" % canary


class FakeResponse:
    def __init__(self, url, body=None):
        self.url = url
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self.request = type("R", (), {"method": "GET"})()
        self._body = body

    def json(self):
        return self._body


class ListeningPage:
    def __init__(self):
        self.handlers = []

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        pass

    def emit(self, response):
        for h in self.handlers:
            h(response)


def bank(url):
    return url.startswith("https://api.bank.example/")


def requests_seeing(*responses):
    page = ListeningPage()
    seen = api_census.Requests(page, bank)
    seen.start()
    for r in responses:
        page.emit(r)
    return seen


def write(tmp_path, **kw):
    kw.setdefault("say", lambda *a: None)
    return failure.write_failure(tmp_path, command="pilot", step="open the statement",
                                 reason="the statement would not open", provider="Bank",
                                 **kw)


# -- what the provider answered --------------------------------------------------

def test_a_letters_id_in_a_requests_path_is_shaped(tmp_path):
    seen = requests_seeing(FakeResponse(
        "https://api.bank.example/v1/merchant/%s/statements" % MERCHANT, {"items": []}))
    assert seen.report()["seen"][0]["path"] == "/v1/merchant/aaaaaaaaaaa9a/statements"
    no_canary_in(write(tmp_path, requests=seen))


def test_a_key_in_an_answer_that_is_an_id_is_shaped(tmp_path):
    seen = requests_seeing(FakeResponse(
        "https://api.bank.example/v1/balances", {MERCHANT: {"balance": 1.0}}))
    no_canary_in(write(tmp_path, requests=seen))


def test_a_query_parameter_named_like_an_id_is_shaped(tmp_path):
    seen = requests_seeing(FakeResponse(
        "https://api.bank.example/v1/docs?%s=1&year=2031" % MERCHANT, {"items": []}))
    no_canary_in(write(tmp_path, requests=seen))


# -- what the page answered about the app's own selectors ---------------------------

class AnsweringPage:
    """A page whose scripts rewrote what it answers."""

    def __init__(self, answer):
        self.answer = answer
        self.url = "https://api.bank.example/list"

    def evaluate(self, script, arg=None):
        if "querySelectorAll" in script and isinstance(arg, list):
            return self.answer
        return {}

    def locator(self, sel):
        raise RuntimeError("not asked")


def test_a_selector_census_entry_is_named_by_the_app_not_the_page(tmp_path):
    page = AnsweringPage([{"name": MERCHANT, "matched": 1, "visible": 1, "nodes": []}])
    out = write(tmp_path, page=page, selectors={"doc_row": "tr.statement"})
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    assert [e["name"] for e in report["selectors"]] == ["doc_row"]
    no_canary_in(out)


def test_a_census_evaluation_is_a_word_of_ours(tmp_path):
    page = AnsweringPage([{"name": "doc_row", "evaluation": SURNAME + " broke it"}])
    no_canary_in(write(tmp_path, page=page, selectors={"doc_row": "tr.statement"}))


def test_a_journal_checkpoint_counts_only_the_selectors_it_asked_about(tmp_path):
    class Page:
        url = "https://api.bank.example/list"

        def evaluate(self, script, arg=None):
            return {"doc_row": [2, 2], MERCHANT: [1, 1],
                    "__page": ["auto", "auto", 900, "complete"]}

    journal = Journal(Page(), {"doc_row": "tr.statement"})
    journal.checkpoint("the list is open")
    assert list(journal.report()["entries"][0]["watching"]) == ["doc_row"]
    no_canary_in(write(tmp_path, journal=journal))


# -- what an app handed over --------------------------------------------------------

def test_a_lowercase_phrase_an_app_handed_over_keeps_only_listed_words(tmp_path):
    """_only_safe kept any lowercase phrase, on the promise that an app
    only hands over words from its own source. A page's words in
    lowercase look the same."""
    out = write(tmp_path, extra={"where": "%s holdings" % SURNAME})
    assert json.loads(Path(out).read_text(encoding="utf-8"))["extra"]["where"] \
        == "aaaaaaaaaaa holdings"
    no_canary_in(out)


def test_a_step_with_a_word_off_the_list_is_shaped(tmp_path):
    out = failure.write_failure(tmp_path, command="pilot",
                                step="open the %s statements" % SURNAME,
                                provider="Bank", say=lambda *a: None)
    assert json.loads(Path(out).read_text(encoding="utf-8"))["step"] \
        == "open the aaaaaaaaaaa statements"
    no_canary_in(out)


def test_the_survey_diagnose_writes_is_held_to_the_same_rule(tmp_path):
    seen = requests_seeing(FakeResponse(
        "https://api.bank.example/v1/merchant/%s" % MERCHANT, {MERCHANT: 1}))
    out = failure.write_survey(tmp_path, provider="Bank", requests=seen,
                               extra={"where": SURNAME}, say=lambda *a: None)
    no_canary_in(out)
