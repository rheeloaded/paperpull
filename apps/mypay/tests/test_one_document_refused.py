"""One document myPay refuses on its own fails alone.

A 401, a 403 or a sign-in page where one document's PDF should be was read
as a sign-out, so the run stopped at that document, and every run after
it, Continue included, stopped at the same document (#124). Now the list
of that document's type is read again with the call Discover reads it
with. A session that ended answers that list with a 401, a 403 or a page
where the list should be, and only that stops the run as signed out. A list
that answers 500, times out or holds no document says nothing of the
session, so the run stops with the list unread and nothing recorded against
the document. A list that still holds its documents leaves the refusal that
document's own, so it fails with nothing saved, the run goes on, and the
next run tries it again. The document is never asked for twice.

Every document, date and page word here is made up, and nothing reaches
DFAS myPay.
"""
import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import mypay_docs as app_mod
import mypay_site as site
from paperpull_core import testkit
from paperpull_core.models import State

DATES = ["2031-06-15", "2031-05-15"]
DOC_IDS = ["21|%s" % d for d in DATES]
PAGE_WORDS = "made-up page words 4417"

# What one document's PDF can be answered with that reads as a sign-out, a
# 401, a 403, and a sign-in page where the PDF should be.
REFUSALS = {
    "401": {"status": 401, "ct": "text/html", "b64": ""},
    "403": {"status": 403, "ct": "text/html", "b64": ""},
    "page": {"status": 200, "ct": "text/html", "b64": base64.b64encode(
        ('<!doctype html><html><title>Sign in</title><input type="password">'
         '<p>%s</p></html>' % PAGE_WORDS).encode()).decode()},
}

# What the history of a type can be answered with once a PDF was refused
# that says the session ended, a page where the list should be (what an
# expired myPay session answers with), or a 401 or a 403.
AFTER = {
    "page": {"status": 200, "html": True},
    "nothing": {"status": 401, "body": {"Succeeded": False}},
    "page 403": {"status": 403, "html": True},
}

# What it can be answered with that says nothing of the session, an error
# page, an error, an answer that did not succeed, no document at all, or no
# answer in time.
UNREAD = {
    "page 500": {"status": 500, "html": True},
    "500": {"status": 500, "body": {"Succeeded": False}},
    "not succeeded": {"status": 200, "body": {"Succeeded": False}},
    "empty": {"status": 200, "body": {"Succeeded": True, "JsonResult": []}},
    "timeout": TimeoutError,
}


class _None:
    def count(self):
        return 0

    def inner_text(self, timeout=None):
        return ""


class Page:
    """The person's own myPay tab. The Retiree Account Statement history
    holds a document for each date, every other type holds none, and each
    PDF is answered by its document's id."""

    def __init__(self, refused=(), how="403", after="list"):
        self.url = "https://mypay.dfas.mil/#/documents"
        self.refused, self.how, self.after = set(refused), how, after
        self.histories, self.pdfs = [], []
        # Whether a PDF was refused, after which the history answers as
        # `after` says.
        self.was_refused = False

    def title(self):
        return "Documents"

    def locator(self, _sel):
        return _None()

    def ids(self):
        return {100 + i: d for i, d in enumerate(DATES)}

    def evaluate(self, js, arg=None):
        if "/api/document/history/" in js:
            self.histories.append(arg)
            if self.after != "list" and self.was_refused:
                answer = {**AFTER, **UNREAD}[self.after]
                if answer is TimeoutError:
                    raise TimeoutError("Timeout 30000ms exceeded")
                return dict(answer)
            rows = [{"Id": i, "DateDiscriminator": d + "T00:00:00", "DataFound": True}
                    for i, d in self.ids().items()] if arg == 21 else []
            return {"status": 200, "body": {"Succeeded": True, "JsonResult": rows}}
        assert "/api/document/pdf/" in js, js
        self.pdfs.append(arg["id"])
        if arg["id"] in self.refused:
            self.was_refused = True
            return dict(REFUSALS[self.how])
        pdf = testkit.text_pdf(["DFAS made-up statement %s" % self.ids()[arg["id"]]])
        return {"status": 200, "ct": "application/pdf", "b64": base64.b64encode(pdf).decode()}


# -- the site ----------------------------------------------------------------

@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_a_document_refused_while_its_list_still_reads_fails_alone(tmp_path, how):
    page = Page(refused={100}, how=how)
    out = tmp_path / "statement.pdf"
    assert site.download_document(page, DOC_IDS[0], out) is False
    assert not out.exists()
    # The PDF is asked for once, never a second time, and the list of its
    # type is read once to find it and once more after the refusal.
    assert page.pdfs == [100]
    assert page.histories == [21, 21]


@pytest.mark.parametrize("after", sorted(AFTER))
@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_a_document_refused_and_a_list_that_will_not_read_after_it_is_a_sign_out(
        tmp_path, how, after):
    page = Page(refused={100}, how=how, after=after)
    out = tmp_path / "statement.pdf"
    with pytest.raises(site.SessionExpired):
        site.download_document(page, DOC_IDS[0], out)
    assert not out.exists()
    assert page.pdfs == [100] and page.histories == [21, 21]


@pytest.mark.parametrize("after", sorted(UNREAD))
def test_a_document_refused_and_a_list_that_does_not_answer_after_it_is_unread(tmp_path, after):
    """A list that answers 500, times out or holds no document was read as
    a sign-out, or its timeout reached the loop as the document's own
    failure and the run went on with no session shown. It says nothing of
    the session, so it stops the run with the list unread."""
    page = Page(refused={100}, how="403", after=after)
    out = tmp_path / "statement.pdf"
    with pytest.raises(site.ListStopped) as got:
        site.download_document(page, DOC_IDS[0], out)
    assert not isinstance(got.value, site.SessionExpired)
    assert not out.exists()
    assert page.pdfs == [100] and page.histories == [21, 21]


def test_a_document_that_comes_is_saved_with_one_read_of_its_list(tmp_path):
    page = Page()
    out = tmp_path / "statement.pdf"
    assert site.download_document(page, DOC_IDS[1], out) is True
    assert out.read_bytes()[:5] == b"%PDF-"
    assert page.pdfs == [101] and page.histories == [21]


def test_discover_reads_each_type_with_the_same_call():
    """The list read again after a refusal is the one Discover reads, so a
    page in its place stops Discover as signed out too. Discover reads any
    page that way, as it did before."""
    page = Page()
    rows = site.collect_documents(page)
    assert [r["doc_id"] for r in rows] == DOC_IDS
    assert page.histories == list(site.DOCUMENT_TYPES)
    page = Page(after="page")
    page.was_refused = True
    with pytest.raises(site.SessionExpired):
        site.collect_documents(page)


# -- the run -------------------------------------------------------------------

def _app(tmp_path):
    out = tmp_path / "out"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "owner": "Dana Example", "output_dir": str(out), "min_pdf_bytes": 10,
        "max_path_length": 240, "delay_min_seconds": 0, "delay_max_seconds": 0}),
        encoding="utf-8")
    args = SimpleNamespace(config=str(cfg), redownload=False, max_docs=None, dry_run=False,
                           start_date=None, end_date=None, year=None, type=None,
                           apply=False, yes=False)
    return app_mod.App(args)


def _run(tmp_path, monkeypatch, capsys, page):
    """The loop over the two statements, the first of them refused, with how
    it ended and what it printed."""
    app = _app(tmp_path)
    monkeypatch.setattr(app, "_on_its_site", lambda: page)
    docs = [app_mod.Document(title="Retiree Account Statement", category="Statement",
                             summary="Retiree Account Statement", date=d, date_text=d,
                             document_id=i) for i, d in zip(DOC_IDS, DATES)]
    ended = None
    try:
        app.process(docs)
    except SystemExit as e:
        ended = e
    return app, docs, ended, " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("how", sorted(REFUSALS))
def test_one_document_refused_while_its_list_reads_fails_alone_and_the_rest_are_saved(
        tmp_path, monkeypatch, capsys, how):
    """The refused document stopped the run before, so the documents after
    it were never asked for, and every later run stopped at it again."""
    page = Page(refused={100}, how=how)
    app, docs, ended, said = _run(tmp_path, monkeypatch, capsys, page)
    assert ended is None, said
    states = {d.document_id: app.progress.get(d.key)["state"] for d in docs}
    assert states == {DOC_IDS[0]: State.FAILED.value, DOC_IDS[1]: State.COMPLETED.value}
    assert (app.stats["failed"], len(app.stats["new_files"])) == (1, 1)
    assert said.count("Nothing was saved, and the next run tries it again") == 1
    assert "signed out" not in said and "sign-in page" not in said
    assert page.pdfs == [100, 101]
    assert not app._already_done(docs[0])
    written = "".join(p.read_text(errors="ignore") for p in app.paths.root.rglob("*")
                      if p.is_file() and p.suffix in (".json", ".csv", ".txt", ".log"))
    assert PAGE_WORDS not in said + written


@pytest.mark.parametrize("after", sorted(AFTER))
def test_one_document_refused_and_its_list_after_it_stop_the_run(tmp_path, monkeypatch,
                                                                 capsys, after):
    page = Page(refused={100}, how="401", after=after)
    app, docs, ended, said = _run(tmp_path, monkeypatch, capsys, page)
    assert isinstance(ended, SystemExit)
    assert "Stopped. Everything downloaded so far is saved." in said
    assert page.pdfs == [100]
    assert app.progress.get(docs[0].key) is None and app.progress.get(docs[1].key) is None
    assert app.stats["failed"] == 0


@pytest.mark.parametrize("after", sorted(UNREAD))
def test_one_document_refused_and_a_list_that_does_not_answer_stop_the_run_unread(
        tmp_path, monkeypatch, capsys, after):
    """The run stops at the refused document with nothing recorded against
    either document, the listing is noted as one that stopped, and the
    panel offers a run that lists first, not Continue, which would read the
    same list for the same document and stop there again (#124)."""
    from paperpull_core import listing
    from paperpull_core.run_reporting import ListNotRead
    page = Page(refused={100}, how="401", after=after)
    app, docs, ended, said = _run(tmp_path, monkeypatch, capsys, page)
    assert isinstance(ended, ListNotRead), (type(ended), said)
    assert "could not be read again" in said
    assert "sign-in page" not in said and "session has expired" not in said
    assert listing.last(app) == listing.STOPPED
    assert page.pdfs == [100]
    assert app.progress.get(docs[0].key) is None and app.progress.get(docs[1].key) is None
    assert app.stats["failed"] == 0
