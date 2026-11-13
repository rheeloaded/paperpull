"""One loan agreement Affirm refuses on its own fails alone.

A 401 or 403 for one agreement was read as a sign-out, so the run stopped
at that agreement. A loan whose agreement Affirm will not give is refused
on every run, so every run stopped there and Continue stopped at it again,
the loop of #124. Now the loan list is read again when one agreement is
refused. A session that ended is refused the list too, and that stops the
run. A list that still reads leaves the agreement failed alone, nothing
saved, and the next run tries it again. The agreement is asked for once.

A list that does not answer when it is read again (a 500, a timeout) or
answers with no loan says nothing either way, so the run stops with the
list unread, nothing recorded against the agreement, and a run that lists
first takes it again. It is neither a sign-out nor the agreement's own
failure (the review of 2026-11-13).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import storage  # noqa: E402,F401  binds this provider's AppSpec
import affirm_site as site  # noqa: E402
import affirm_docs as docs  # noqa: E402
from paperpull_core import receipt_pdf, testkit  # noqa: E402
from paperpull_core.run_reporting import ListNotRead  # noqa: E402

LOANS = ("L-0001", "L-0002", "L-0003")
DAYS = {"L-0001": "2025-11-26", "L-0002": "2024-06-02", "L-0003": "2023-01-15"}


def terms_of(loan):
    return "https://www.affirm.com/api/v2/disclosures/T%s/view" % loan[-4:]


def details_of(loan):
    item = {"label": {"value": "Loan terms"},
            "action": {"name": "OPEN_URL", "data": {"url": terms_of(loan), "external": False}}}
    return {"modules": {"tabs": {"data": {"tabs": {"details": {"data": {"modules": {
        "disclosures": {"data": {"items": [item]}}}}}}}}}}


class Locator:
    def count(self):
        return 0


class Page:
    """A signed-in affirm.com page. The loan list and each loan's details
    answer from the API, and each agreement from its own address, refused
    with `how` for the loans in `refused`. A session that ends at the
    refusal (`signs_out`) refuses the list from then on, and one whose list
    stops answering then (`list_then`, a status, "timeout" or "empty")
    answers it that way."""

    url = "https://www.affirm.com/u/"

    def __init__(self, refused=(), how=401, signs_out=False, list_then=None):
        self.refused, self.how = set(refused), how
        self.list_then = 401 if signs_out else list_then
        self.list_status = 200
        self.list_json = None
        self.asked = []

    def locator(self, selector):
        return Locator()

    def evaluate(self, js, arg=None):
        self.asked.append(arg)
        if arg.startswith(site.API["loans"]):
            if self.list_status == "timeout":
                raise TimeoutError("Timeout 30000ms exceeded")
            if self.list_status != 200:
                return {"status": self.list_status, "json": None, "url": arg}
            if self.list_json is not None:
                return {"status": 200, "json": self.list_json, "url": arg}
            return {"status": 200, "json": {"data": [{"id": x, "merchant_name": "Example Cycles"}
                                                     for x in LOANS], "next": None}, "url": arg}
        if arg.startswith("/api/purchase-management/loans/"):
            return {"status": 200, "json": details_of(arg.rsplit("/", 1)[1]), "url": arg}
        loan = next(x for x in LOANS if terms_of(x) == arg)
        if loan in self.refused:
            if self.list_then == "empty":
                self.list_json = {"data": [], "next": None}
            elif self.list_then is not None:
                self.list_status = self.list_then
            return {"status": self.how, "ct": "text/html", "text": "", "url": arg}
        html = "<html><body>" + "Truth in Lending made-up words " * 100 + "</body></html>"
        return {"status": 200, "ct": "text/html; charset=utf-8", "text": html, "url": arg}

    def lists_asked(self):
        return sum(1 for a in self.asked if a.startswith(site.API["loans"]))

    def agreements_asked(self):
        return [a for a in self.asked if a.startswith("https://")]


@pytest.fixture
def rendered(monkeypatch):
    def render(page, html, out_path):
        Path(out_path).write_bytes(testkit.text_pdf(["Affirm made-up loan agreement"]))
    monkeypatch.setattr(receipt_pdf, "print_html_to_pdf", render)


def take(page, out, loan="L-0002"):
    return site.download_document(page, "Loan Agreement", DAYS[loan], out, item_hint=loan,
                                  client_hint=terms_of(loan))


@pytest.mark.parametrize("how", [401, 403])
def test_an_agreement_refused_while_the_list_still_reads_fails_alone(rendered, tmp_path, how):
    page = Page(refused={"L-0002"}, how=how)
    out = tmp_path / "a.pdf"
    assert take(page, out) is False
    assert not out.exists()
    # The loan list is read once after the refusal, and the agreement is
    # asked for once, never a second time.
    assert page.lists_asked() == 1
    assert page.agreements_asked() == [terms_of("L-0002")]


@pytest.mark.parametrize("how", [401, 403])
def test_an_agreement_refused_and_the_list_refused_after_it_is_a_sign_out(rendered, tmp_path, how):
    page = Page(refused={"L-0002"}, how=how, signs_out=True)
    out = tmp_path / "a.pdf"
    with pytest.raises(site.SessionExpired):
        take(page, out)
    assert not out.exists()
    assert page.agreements_asked() == [terms_of("L-0002")]


@pytest.mark.parametrize("answer", [{}, {"data": [], "next": None}])
def test_a_list_read_empty_after_a_refusal_is_unread_not_a_sign_out(rendered, tmp_path, answer):
    """No loans at all is not a list that still reads, since this loan was
    listed, and nothing in it says the session ended."""
    page = Page(refused={"L-0002"})
    page.list_json = answer
    with pytest.raises(site.ListStopped):
        take(page, tmp_path / "a.pdf")
    assert page.agreements_asked() == [terms_of("L-0002")]


@pytest.mark.parametrize("then", [500, 503, "timeout"])
def test_a_list_that_does_not_answer_after_a_refusal_is_unread(rendered, tmp_path, then):
    page = Page(refused={"L-0002"}, list_then=then)
    out = tmp_path / "a.pdf"
    with pytest.raises(site.ListStopped):
        take(page, out)
    assert not out.exists()
    assert page.lists_asked() == 1
    assert page.agreements_asked() == [terms_of("L-0002")]


def test_an_agreement_given_reads_no_list(rendered, tmp_path):
    page = Page()
    out = tmp_path / "a.pdf"
    assert take(page, out)
    assert page.lists_asked() == 0


def make_app(tmp):
    config = json.loads((HERE / "config.example.json").read_text())
    config.update({"owner": "Tester Example", "output_dir": str(Path(tmp) / "out"),
                   "delay_min_seconds": 0, "delay_max_seconds": 0})
    cfg = Path(tmp) / "config.json"
    cfg.write_text(json.dumps(config))
    return docs.App(docs.build_parser().parse_args(["--resume", "--config", str(cfg)]))


def run_with(tmp_path, page):
    """A Run All's downloads over three listed agreements, with what it
    printed."""
    app = make_app(tmp_path)
    for loan in LOANS:
        app._record_statement_doc({"title": "Loan Agreement", "date": DAYS[loan], "account": "Example Cycles",
                                   "category": "Loan Agreement", "item_id": loan,
                                   "client_id": terms_of(loan), "href": terms_of(loan)})
    app.discovery.save()
    app.check_session = lambda p: None
    app._on_its_site = lambda: page
    app._delay = lambda *a, **k: None
    seen = io.StringIO()
    ended = None
    try:
        with redirect_stdout(seen):
            app.process(app._select())
    except SystemExit as e:
        ended = e
    return app, ended, seen.getvalue()


def test_one_agreement_refused_while_the_list_reads_fails_alone_and_the_rest_are_saved(rendered, tmp_path):
    """The refused agreement stopped the run before, so the ones after it
    were never asked for, and every later run stopped at it again."""
    page = Page(refused={"L-0002"}, how=403)
    app, ended, said = run_with(tmp_path, page)
    assert ended is None, said
    states = {v["item_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"L-0001": "Completed", "L-0002": "Failed", "L-0003": "Completed"}
    assert (app.stats["failed"], len(app.stats["new_files"])) == (1, 2)
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert "session has expired" not in said
    assert page.agreements_asked().count(terms_of("L-0002")) == 1


def test_one_agreement_refused_and_the_list_after_it_stop_the_run(rendered, tmp_path):
    page = Page(refused={"L-0001"}, how=401, signs_out=True)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, SystemExit)
    assert "session has expired" in said
    assert "Nothing was saved" not in said
    assert app.progress.data == {}
    assert page.agreements_asked() == [terms_of("L-0001")]


@pytest.mark.parametrize("then", [500, "timeout", "empty"])
def test_one_agreement_refused_and_the_list_unread_after_it_stop_with_the_list_unread(
        rendered, tmp_path, then):
    """A 500 or a timeout there reached the loop as the agreement's own
    failure, and the run went on with no session shown. A list with no loan
    was read as a sign-out. Now the run stops with the list unread, nothing
    recorded against the agreement, so Get new documents takes it again."""
    page = Page(refused={"L-0002"}, how=403, list_then=then)
    app, ended, said = run_with(tmp_path, page)
    assert isinstance(ended, ListNotRead), said
    states = {v["item_id"]: v["state"] for v in app.progress.data.values()}
    assert states == {"L-0001": "Completed"}
    assert app.stats["failed"] == 0
    assert "session has expired" not in said
    assert "Nothing was saved" not in said
    assert "could not be read again" in said
    assert page.agreements_asked() == [terms_of("L-0001"), terms_of("L-0002")]

