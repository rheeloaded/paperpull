"""PayPal's business download path, run end to end without a browser.

0.34.0 passed deliver() a keyword it did not take, and every document four
apps asked for failed before anything was pressed, with every handover test
passing, because none of them ran process() or download_one(). This runs
both for business statements, with the page and the site layer stood in
for and the capture replaced by paperpull_core.testkit, which holds every
call to deliver's and place's real signatures.
"""
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import storage  # noqa: F401  binds this provider's AppSpec
import paypal_docs as app_mod
import paypal_site as site
from paperpull_core import delivery, identity
from paperpull_core.journal import Journal
from paperpull_core.testkit import StrictDelivery, sample_pdf

DAYS = [("2031-08-01", "2031-08-31"), ("2031-07-01", "2031-07-31"), ("2031-06-01", "2031-06-30")]


class _Store:
    def __init__(self, data=None):
        self.data = data or {}
        self.written = {}

    def update(self, key, value, *a, **kw):
        self.written.setdefault(key, {}).update(value)

    def append_rows(self, *a, **kw):
        pass


class _Paths:
    def __init__(self, root):
        self.root, self.manual_review = root, root / "review"
        self.manual_review.mkdir()

    def folder_for(self, *a):
        return self.root


class Checked(StrictDelivery):
    """The stand-in, with a delivery that says the statement named its days,
    as the real one says once it has read the file."""

    def _fake(self, name):
        fake = super()._fake(name)

        def checked(*args, **kwargs):
            got = fake(*args, **kwargs)
            return delivery.Delivery(got.outcome, got.mechanism,
                                     identity.Verdict(identity.VERIFIED, ("date",), ("date",)))
        checked.__name__ = name
        return checked


class Refused(StrictDelivery):
    """The stand-in, with a delivery that says the statement named other
    days than it was listed under, as the real one says of one it placed
    when it is not strict. `checked` is what it had of its own to check."""

    def __init__(self, *a, checked=("date", "start"), **kw):
        super().__init__(*a, **kw)
        self.checked = tuple(checked)

    def _fake(self, name):
        fake = super()._fake(name)

        def refused(*args, **kwargs):
            got = fake(*args, **kwargs)
            return delivery.Delivery(got.outcome, got.mechanism,
                                     identity.Verdict(identity.REFUSED, self.checked, ()))
        refused.__name__ = name
        return refused


def _docs():
    out = []
    for first, last in DAYS:
        ref = site.Period(start=first, end=last)
        out.append(app_mod.Document(title=ref.title(), category="Statement",
                                    summary="Monthly Statement", date=last, href=ref.href()))
    return out


def _app(tmp_path, monkeypatch, handed=None):
    app = object.__new__(app_mod.App)
    app.config = {"max_path_length": 240, "min_pdf_bytes": 2000}
    app.paths = _Paths(tmp_path)
    app.stats = defaultdict(int, new_files=[], dates=[])
    app.progress = app.index_csv = _Store()
    app.discovery = _Store({d.key: d.to_dict() for d in _docs()})
    app._journal = Journal()
    app._dl_dir = None
    app._business = False
    app._reports = None
    app._unlisted = None
    app._listing_cut_short = False
    failures = []
    app.page = lambda: object()
    app.check_session = lambda page: None
    # The tab here is a stand-in with no address, so the check that it is
    # on the provider's own site (tabs.on_its_site) is stood in for too.
    app._on_its_site = lambda: app.page()
    app._delay = lambda *a, **kw: None
    app._already_done = lambda doc: False
    app.write_failure = lambda *a, **kw: failures.append(a)
    app._business_view = lambda page: SimpleNamespace(listed=True)
    pressed = []

    def request(page, ref, view, rivals=()):
        pressed.append(ref)
        return (delivery.DocumentRequest(trigger=lambda: None, expect=ref.identity(),
                                         rivals=tuple(rivals), close_new_tabs=True), "")
    monkeypatch.setattr(site, "statement_request", request)
    monkeypatch.setattr(site, "taken_from_the_page", lambda page, out: handed)
    return app, failures, pressed


def test_a_run_reaches_the_capture_with_arguments_it_accepts(tmp_path, monkeypatch):
    spy = Checked().install(monkeypatch)
    app, failures, pressed = _app(tmp_path, monkeypatch)
    app.process(_docs())
    assert [c.name for c in spy.calls] == ["deliver"] * 3
    assert app.stats["failed"] == 0, "a call the capture refused"
    assert len(app.stats["new_files"]) == 3 and not failures
    first = spy.calls[0].arguments
    assert first["rivals"], "the rows it could be confused with never arrived"
    assert first["strict"] is False, "a refusal would destroy a statement the check got wrong"
    assert first["settle_ms"] == site.BUSINESS_SETTLE_MS
    assert first["is_safe_url"] is site.is_safe_url
    assert first["request"].close_new_tabs is True
    assert [ref.end for ref in pressed] == [last for _first, last in DAYS]


def test_a_statement_whose_days_were_not_checked_goes_to_review_not_the_archive(
        tmp_path, monkeypatch):
    """The stand-in's delivery says nothing of the file's days, the way a
    scan or a statement known only by the day it was made comes back."""
    StrictDelivery().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert app.stats["manual_review"] == 1 and not app.stats["new_files"]
    assert not list(tmp_path.glob("*.pdf"))
    assert len(list((tmp_path / "review").glob("*.pdf"))) == 1


def test_nothing_arriving_is_a_capture_failure_not_a_crash(tmp_path, monkeypatch):
    spy = StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, failures, _pressed = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert [c.name for c in spy.calls] == ["deliver"]
    assert app.stats["failed"] == 0
    assert app.stats["manual_review"] == 1 and failures


def test_what_the_page_saved_is_placed_through_the_same_check(tmp_path, monkeypatch):
    """No download came, and the page's own blob or address had the
    statement. It is staged and checked the same way, by place."""
    spy = StrictDelivery(outcome=delivery.NOTHING).install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch, handed=sample_pdf())
    app.process(_docs()[:1])
    assert [c.name for c in spy.calls] == ["deliver", "place"]
    placed = spy.calls[1].arguments
    assert placed["strict"] is False and placed["expect"] == site.Period(*DAYS[0]).identity()
    assert placed["data"][:5] == b"%PDF-"


def test_with_refuse_wrong_documents_set_a_refused_statement_is_destroyed_by_the_app(
        tmp_path, monkeypatch, capsys):
    """The delivery is never strict, so it never destroys one itself, and
    the app destroys a refused statement that had a day of its own to be
    checked by."""
    spy = Refused().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    app.config["refuse_wrong_documents"] = True
    app.process(_docs()[:1])
    assert spy.calls[0].arguments["strict"] is False
    assert not list(tmp_path.glob("*.pdf")) and not list((tmp_path / "review").glob("*.pdf"))
    assert app.stats["wrong_document"] == 1 and app.stats["manual_review"] == 1
    assert "The file was destroyed" in " ".join(capsys.readouterr().out.split())


def test_a_refused_statement_with_nothing_of_its_own_checked_is_never_destroyed(
        tmp_path, monkeypatch, capsys):
    """Its first and last day were both other statements' days too, so
    nothing of its own was there to count and nothing says it is not this
    one. With refuse_wrong_documents set it was destroyed. It waits in
    Manual Review."""
    Refused(checked=()).install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    app.config["refuse_wrong_documents"] = True
    app.process(_docs()[:1])
    assert not list(tmp_path.glob("*.pdf")), "it was filed in the archive"
    assert len(list((tmp_path / "review").glob("*.pdf"))) == 1
    assert app.stats["wrong_document"] == 0 and app.stats["manual_review"] == 1
    said = " ".join(capsys.readouterr().out.split())
    assert "destroyed" not in said and "put in Manual Review" in said


def test_a_refused_statement_that_cannot_be_destroyed_goes_to_review(tmp_path, monkeypatch):
    Refused().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    app.config["refuse_wrong_documents"] = True
    real = Path.unlink

    def held(self, *a, **kw):
        if self.parent == tmp_path and self.suffix == ".pdf":
            raise OSError("held by another program")
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", held)
    app.process(_docs()[:1])
    assert not list(tmp_path.glob("*.pdf")), "left in the archive under its name"
    assert len(list((tmp_path / "review").glob("*.pdf"))) == 1
    assert app.stats["wrong_document"] == 0 and app.stats["manual_review"] == 1


def test_a_statement_naming_other_days_goes_to_review_with_a_note_saying_so(
        tmp_path, monkeypatch, capsys):
    spy = Refused().install(monkeypatch)
    app, failures, _pressed = _app(tmp_path, monkeypatch)
    app.process(_docs()[:1])
    assert spy.calls[0].arguments["strict"] is False
    assert app.stats["manual_review"] == 1 and not app.stats["new_files"]
    assert not list(tmp_path.glob("*.pdf")), "it was filed in the archive"
    assert len(list((tmp_path / "review").glob("*.pdf"))) == 1
    said = " ".join(capsys.readouterr().out.split())
    assert "It names other days than it was listed under, so it was put in Manual Review" in said
    assert "could not be checked" not in said
    assert failures and failures[0][1] == "it names other days than it was listed under"


def _held(monkeypatch, tmp_path, move=False, copy=False, remove=False):
    """Make moving the statement to Manual Review, copying it there and
    removing it from the archive fail, as each does while a sync client or
    a virus scanner holds a file."""
    replace, unlink, copyfile = Path.replace, Path.unlink, app_mod.shutil.copyfile

    def moved(self, target):
        if move and Path(target).parent == tmp_path / "review":
            raise OSError("held by another program")
        return replace(self, target)

    def removed(self, *a, **kw):
        if remove and self.parent == tmp_path and self.suffix == ".pdf":
            raise OSError("held by another program")
        return unlink(self, *a, **kw)

    def copied(source, target, *a, **kw):
        if copy:
            Path(target).write_bytes(b"%PDF-")
            raise OSError("held by another program")
        return copyfile(source, target, *a, **kw)
    monkeypatch.setattr(Path, "replace", moved)
    monkeypatch.setattr(Path, "unlink", removed)
    monkeypatch.setattr(app_mod.shutil, "copyfile", copied)


def _record(app):
    (only,) = app.progress.written.values()
    return only


def test_a_statement_that_cannot_be_moved_to_review_is_copied_there(
        tmp_path, monkeypatch, capsys):
    """Moving it to Manual Review failed. It used to be removed and kept
    nowhere. It is copied there, then removed from the archive."""
    Refused().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    _held(monkeypatch, tmp_path, move=True)
    app.process(_docs()[:1])
    assert not list(tmp_path.glob("*.pdf")), "left in the archive under its name"
    kept = list((tmp_path / "review").glob("*.pdf"))
    assert len(kept) == 1 and kept[0].read_bytes()[:5] == b"%PDF-"
    assert _record(app)["pdf_path"] == str(kept[0])
    said = " ".join(capsys.readouterr().out.split())
    assert "so it was put in Manual Review" in said


def test_a_statement_that_cannot_be_moved_or_copied_is_never_left_under_its_name(
        tmp_path, monkeypatch, capsys):
    Refused().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    _held(monkeypatch, tmp_path, move=True, copy=True)
    app.process(_docs()[:1])
    assert not list(tmp_path.glob("*.pdf")), "left in the archive under its name"
    assert not list((tmp_path / "review").glob("*.pdf")), "a part of a copy was left"
    assert _record(app)["pdf_path"] == "" and app.stats["manual_review"] == 1
    said = " ".join(capsys.readouterr().out.split())
    assert "could not be moved to Manual Review, so it was not kept" in said


@pytest.mark.parametrize("copy", [False, True], ids=["copied", "not copied"])
def test_a_statement_that_cannot_be_removed_either_is_pointed_at_where_it_is(
        tmp_path, monkeypatch, capsys, copy):
    """Removing it failed too. Its record said it was not kept, with the
    statement still in the archive under the name it would have been filed
    by. The record points at it there now, and says so."""
    Refused().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    _held(monkeypatch, tmp_path, move=True, copy=copy, remove=True)
    app.process(_docs()[:1])
    (left,) = list(tmp_path.glob("*.pdf"))
    record = _record(app)
    assert record["pdf_path"] == str(left)
    assert "still there under the name it would have been filed by" in record["notes"]
    assert ("with a copy in Manual Review" in record["notes"]) is (not copy)
    said = " ".join(capsys.readouterr().out.split())
    assert "still there under the name it would have been filed by" in said
    assert "not kept" not in said


def test_two_statements_ending_on_the_same_day_are_told_apart_by_their_first_days(
        tmp_path, monkeypatch):
    """Both would be filed by one name. The second used to get " (2)",
    which names whichever was saved second. It gets the first day it
    covers, the same name on every run."""
    Checked().install(monkeypatch)
    app, _failures, _pressed = _app(tmp_path, monkeypatch)
    docs = []
    for first in ("2031-07-01", "2031-06-01"):
        ref = site.Period(start=first, end="2031-08-31")
        docs.append(app_mod.Document(title=ref.title(), category="Statement",
                                     summary="Statement", date=ref.end, href=ref.href()))
    app.process(docs)
    names = sorted((p.name for p in tmp_path.glob("*.pdf")), key=len)
    assert len(names) == 2, names
    plain, marked = names
    assert marked == plain[:-len(".pdf")] + " 2031-06-01.pdf", names


def test_the_stand_in_refuses_what_the_real_call_would():
    """If this passed a keyword deliver() does not take, the tests above
    would fail the way 0.34.0 failed on a real account."""
    with pytest.raises(TypeError):
        StrictDelivery()._fake("deliver")(
            object(), delivery.DocumentRequest(), "x.pdf",
            is_safe_url=lambda u: True, not_a_real_keyword=1)
